import { withCache, jsonResponse } from './_shared.js';

// Replaced OECD CLI (blocked by IP) with Chicago Fed CFNAI
// CFNAI-MA3 > 0    = above-trend growth → bullish (+1 score)
// CFNAI-MA3 < -0.70 = historical recession threshold → risk-off

function analyseCfnai(ma3Series, rawSeries) {
  if (!ma3Series?.length) return null;
  const latest = ma3Series[ma3Series.length - 1];
  const v = latest.value;
  let signal, color, isBullish;
  if (v > 0.20)       { signal = 'Strong Expansion ↑'; color = 'green';  isBullish = true;  }
  else if (v > 0)     { signal = 'Expanding ↑';        color = 'green';  isBullish = true;  }
  else if (v > -0.70) { signal = 'Below Trend ↓';      color = 'amber';  isBullish = false; }
  else                { signal = 'Recession Risk ↓';   color = 'red';    isBullish = false; }
  return {
    ma3Series, rawSeries: rawSeries ?? [],
    ma3Latest: v, ma3LatestDate: latest.date,
    rawLatest: rawSeries?.length ? rawSeries[rawSeries.length - 1].value : null,
    rawLatestDate: rawSeries?.length ? rawSeries[rawSeries.length - 1].date : null,
    signal, color, isBullish,
  };
}

async function fredFetch(url) {
  // Try twice — transient FRED failures are common
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const r = await fetch(url, { signal: AbortSignal.timeout(12000) });
      if (r.ok) return r.json();
    } catch { /* retry */ }
  }
  return null;
}

export const onRequestGet = async (ctx) => {
  return withCache(ctx, 'cfnai-v3', 21600, async () => {
    const fredKey = ctx.env.FRED_API_KEY;
    if (!fredKey) return { error: 'No FRED API key', isBullish: false, scored: false };

    const base = `https://api.stlouisfed.org/fred/series/observations?api_key=${fredKey}&file_type=json&sort_order=asc&observation_start=2004-01-01`;
    const [ma3Body, rawBody] = await Promise.all([
      fredFetch(`${base}&series_id=CFNAIMA3`),
      fredFetch(`${base}&series_id=CFNAI`),
    ]);

    const parseSeries = body => (body?.observations ?? [])
      .map(o => ({ date: o.date.slice(0, 7), value: parseFloat(o.value) }))
      .filter(p => !isNaN(p.value));

    const ma3Series = parseSeries(ma3Body);
    const rawSeries = parseSeries(rawBody);
    if (!ma3Series.length) return { error: 'No CFNAI data from FRED', isBullish: false, scored: false };

    const result = analyseCfnai(ma3Series, rawSeries);
    return { ...result, scored: result.isBullish, source: 'FRED (CFNAI)', fetchedAt: new Date().toISOString() };
  });
};
