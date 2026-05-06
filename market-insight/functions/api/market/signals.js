import { toMap, rolling200, withCache, yf, yfetch, jsonResponse } from './_shared.js';

function determinePhase(score) {
  if (score >= 5) return { phase: 'PHASE 1 — GREEN',   color: 'green'  };
  if (score >= 3) return { phase: 'PHASE 2-3 — WATCH', color: 'yellow' };
  return            { phase: 'PHASE 4 — RED',           color: 'red'    };
}

function getCloses(result) {
  return (result?.indicators?.quote?.[0]?.close ?? []).filter(c => c != null);
}

export const onRequestGet = async (ctx) => {
  return withCache(ctx, 'signals', 21600, async () => {
    const fredKey = ctx.env.FRED_API_KEY;

    const fetches = [
      yfetch(yf('SOXX',    '1d', 'max')),
      yfetch(yf('QQQ',     '1d', 'max')),
      yfetch(yf('SPY',     '1d', '1y')),
      yfetch(yf('RSP',     '1d', '1y')),
      yfetch(yf('^VIX',   '1wk', '2y')),
      yfetch(yf('^VIX3M', '1wk', '2y')),
      fredKey
        ? fetch(`https://api.stlouisfed.org/fred/series/observations?series_id=IC4WSA&api_key=${fredKey}&file_type=json&sort_order=desc&limit=10`,
            { signal: AbortSignal.timeout(10000) }).then(r => r.ok ? r.json() : null).catch(() => null)
        : Promise.resolve(null),
    ];

    const [soxxData, qqqData, spyData, rspData, vixData, vix3mData, claimsBody] = await Promise.all(fetches);

    const soxxR = soxxData?.chart?.result?.[0];
    const qqqR  = qqqData?.chart?.result?.[0];
    const spyR  = spyData?.chart?.result?.[0];
    const rspR  = rspData?.chart?.result?.[0];
    const vixR  = vixData?.chart?.result?.[0];
    const vix3R = vix3mData?.chart?.result?.[0];

    // 1. SOXX/QQQ ratio vs 200 SMA
    const soxxMap  = toMap(soxxR);
    const qqqMap   = toMap(qqqR);
    const ratDates = [...soxxMap.keys()].filter(d => qqqMap.has(d)).sort();
    const ratVals  = ratDates.map(d => soxxMap.get(d) / qqqMap.get(d));
    const ratSma200 = rolling200(ratVals);
    const ratLatest = ratVals.length ? ratVals[ratVals.length - 1] : null;
    const soxxQqqRatio = {
      value: ratLatest, sma200: ratSma200,
      status: (ratSma200 != null && ratLatest != null && ratLatest > ratSma200) ? 'Bullish' : 'Bearish',
      unavailable: ratLatest == null,
    };

    // 2. VIX term structure
    const vixMap   = toMap(vixR);
    const vix3mMap = toMap(vix3R);
    const vixDates = [...vixMap.keys()].filter(d => vix3mMap.has(d)).sort();
    const lastVixDate = vixDates[vixDates.length - 1];
    const vixRatio = lastVixDate ? vixMap.get(lastVixDate) / vix3mMap.get(lastVixDate) : null;
    const vixStructure = {
      ratio: vixRatio,
      status: vixRatio == null ? 'N/A' : vixRatio > 1.05 ? 'Panic' : vixRatio < 0.85 ? 'Complacent' : 'Neutral',
      unavailable: vixRatio == null,
    };

    // 3. Index health (1y distance from high)
    const pctFromHigh = (closes) => {
      if (!closes.length) return null;
      const high = Math.max(...closes);
      if (high === 0) return null;
      return ((high - closes[closes.length - 1]) / high) * 100;
    };
    const spyPct  = pctFromHigh(getCloses(spyR));
    const qqqPct  = pctFromHigh(getCloses(qqqR).slice(-252));
    const soxxPct = pctFromHigh(getCloses(soxxR).slice(-252));
    const avgDistFromHigh = (spyPct != null && qqqPct != null && soxxPct != null)
      ? (spyPct + qqqPct + soxxPct) / 3 : null;
    const indexHealth = {
      avgDistFromHigh, spy: spyPct, qqq: qqqPct, soxx: soxxPct,
      unavailable: avgDistFromHigh == null,
    };

    // 4. Breadth (RSP/SPY vs 200 SMA)
    const spyMap1y = toMap(spyR);
    const rspMap   = toMap(rspR);
    const bDates   = [...spyMap1y.keys()].filter(d => rspMap.has(d)).sort();
    const bVals    = bDates.map(d => rspMap.get(d) / spyMap1y.get(d));
    const bSma200  = rolling200(bVals);
    const bLatest  = bVals.length ? bVals[bVals.length - 1] : null;
    const breadth  = {
      ratio: bLatest, sma200: bSma200,
      status: (bSma200 != null && bLatest != null && bLatest > bSma200) ? 'Healthy' : 'Narrow',
      unavailable: bLatest == null,
    };

    // 5. Macro floor (FRED claims)
    let macroFloor = { current: 0, previous: 0, isImproving: false, unavailable: true };
    if (claimsBody) {
      const obs = (claimsBody.observations ?? [])
        .map(o => parseFloat(o.value)).filter(v => !isNaN(v)).reverse();
      if (obs.length >= 5) {
        macroFloor = {
          current: obs[obs.length - 1],
          previous: obs[obs.length - 2],
          isImproving: obs[obs.length - 1] < obs[obs.length - 5],
          unavailable: false,
        };
      }
    }

    // 6. OECD CLI — best-effort; scores 0 if unavailable
    const cli = { usa: false, g7: false, isBullish: false };

    let score = 0;
    if (!soxxQqqRatio.unavailable && soxxQqqRatio.status === 'Bullish') score++;
    if (!vixStructure.unavailable && vixStructure.ratio < 1.0)          score++;
    if (!indexHealth.unavailable  && indexHealth.avgDistFromHigh < 5)   score++;
    if (!breadth.unavailable      && breadth.status === 'Healthy')      score++;
    if (!macroFloor.unavailable   && macroFloor.isImproving)            score++;
    if (cli.isBullish)                                                   score++;

    const { phase, color } = determinePhase(score);

    const fmtRatio = v => v != null ? v.toFixed(4) : 'N/A';
    const fmtVix   = v => v != null ? v.toFixed(3) : 'N/A';
    const fmtDist  = v => v != null ? `Avg ${v.toFixed(1)}% from high` : 'Data unavailable';

    const scoreBreakdown = [
      { indicator: 'SOX/QQQ Ratio', scored: !soxxQqqRatio.unavailable && soxxQqqRatio.status === 'Bullish',
        value: soxxQqqRatio.unavailable ? 'Data unavailable' : `${soxxQqqRatio.status} — ratio ${fmtRatio(ratLatest)}` },
      { indicator: 'VIX Structure', scored: !vixStructure.unavailable && vixStructure.ratio < 1.0,
        value: vixStructure.unavailable ? 'Data unavailable' : `${vixStructure.status} — ratio ${fmtVix(vixRatio)}` },
      { indicator: 'Index Health',  scored: !indexHealth.unavailable && indexHealth.avgDistFromHigh < 5,
        value: fmtDist(avgDistFromHigh) },
      { indicator: 'Breadth',       scored: !breadth.unavailable && breadth.status === 'Healthy',
        value: breadth.unavailable ? 'Data unavailable' : `${breadth.status} — RSP/SPY ${fmtRatio(bLatest)}` },
      { indicator: 'Macro Floor',   scored: !macroFloor.unavailable && macroFloor.isImproving,
        value: macroFloor.unavailable ? 'No FRED data' : `Claims ${macroFloor.isImproving ? 'improving' : 'worsening'} (${Math.round(macroFloor.current).toLocaleString()}K)` },
      { indicator: 'OECD CLI',      scored: cli.isBullish, value: 'See CLI section below' },
    ];

    return { phase, score, color, scoreBreakdown, metrics: { soxxQqqRatio, vixStructure, indexHealth, breadth, macroFloor, cli } };
  });
};
