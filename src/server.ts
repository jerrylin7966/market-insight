import 'dotenv/config';
import axios from 'axios';
import express, { Request, Response, NextFunction } from 'express';
import cors from 'cors';
import path from 'path';
import { startScheduler } from './scheduler';
import { runAllFetchers } from './fetchers';
import { sendWeeklyEmail } from './mailer';
import { getLatestSnapshots, getSnapshotHistory, upsertManualBalance, getOAuthToken } from './db';
import { buildAuthUrl, exchangeCode } from './fetchers/truelayer';
import { PLATFORMS } from './types';
import type { ManualUpdatePayload } from './types';

const app  = express();
const PORT = parseInt(process.env.PORT ?? '3000', 10);

app.use(cors());
app.use(express.json());

function auth(req: Request, res: Response, next: NextFunction): void {
  const password = process.env.DASHBOARD_PASSWORD ?? 'changeme';
  const header   = req.headers.authorization;
  if (!header) { res.setHeader('WWW-Authenticate', 'Basic realm="Asset Hub"'); res.status(401).json({ error: 'Auth required' }); return; }
  const decoded = Buffer.from(header.split(' ')[1], 'base64').toString('utf8');
  const pass    = decoded.split(':')[1];
  if (pass !== password) { res.status(401).json({ error: 'Invalid password' }); return; }
  next();
}

app.get('/api/summary', auth, (req, res) => {
  const snapshots = getLatestSnapshots();
  const totalUsd  = snapshots.reduce((sum, s) => sum + s.balance_usd, 0);
  const platforms = Object.values(PLATFORMS).map(meta => {
    const snap = snapshots.find((s: any) => s.platform === meta.id);
    return {
      ...meta,
      balanceUsd:    snap?.balance_usd    ?? null,
      balanceNative: snap?.balance_native ?? null,
      currency:      snap?.currency       ?? meta.currency,
      fxRate:        snap?.fx_rate        ?? null,
      lastUpdated:   snap?.date           ?? null,
      hasError:      !snap,
    };
  });
  res.json({ totalUsd, platforms, asOf: new Date().toISOString() });
});

app.get('/api/history', auth, (req, res) => {
  const days = parseInt(req.query.days as string ?? '90', 10);
  res.json(getSnapshotHistory(days));
});

app.post('/api/manual', auth, (req: Request<{}, {}, ManualUpdatePayload>, res) => {
  const { platform, balanceNative } = req.body;
  if (!['revolut_balance','revolut_stocks','revolut_crypto','tiger','china_bank','ctbc_balance','ctbc_stocks','dbs'].includes(platform)) { res.status(400).json({ error: 'Platform does not support manual updates' }); return; }
  if (typeof balanceNative !== 'number' || balanceNative < 0) { res.status(400).json({ error: 'Invalid amount' }); return; }
  upsertManualBalance(platform, balanceNative);
  res.json({ ok: true, platform, balanceNative, updatedAt: new Date().toISOString() });
});

app.get('/api/market/vix', auth, async (req, res) => {
  try {
    const [vixRes, vxvRes] = await Promise.all([
      axios.get('https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?interval=1wk&range=2y', { timeout: 10000 }),
      axios.get('https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX3M?interval=1wk&range=2y', { timeout: 10000 }),
    ]);
    const vixResult = vixRes.data?.chart?.result?.[0];
    const vxvResult = vxvRes.data?.chart?.result?.[0];
    if (!vixResult || !vxvResult) { res.status(502).json({ error: 'No data from Yahoo Finance' }); return; }

    const toMap = (result: any): Map<string, number> => {
      const ts: number[]            = result.timestamp ?? [];
      const closes: (number|null)[] = result.indicators?.quote?.[0]?.close ?? [];
      const m = new Map<string, number>();
      ts.forEach((t, i) => { if (closes[i] != null) m.set(new Date(t * 1000).toISOString().slice(0, 10), closes[i]!); });
      return m;
    };

    const vixMap  = toMap(vixResult);
    const vxvMap  = toMap(vxvResult);
    const dates   = [...vixMap.keys()].filter(d => vxvMap.has(d)).sort();
    const series  = dates.map(d => ({ date: d, vix: vixMap.get(d), vxv: vxvMap.get(d), ratio: vixMap.get(d)! / vxvMap.get(d)! }));
    const lastRatio = series[series.length - 1]?.ratio ?? 1;
    let state: string;
    let uiColor: string;
    if (lastRatio < 0.85)       { state = 'EXTREME COMPLACENCY'; uiColor = 'red';   }
    else if (lastRatio > 1.05)  { state = 'PANIC / OPPORTUNITY'; uiColor = 'green'; }
    else                        { state = 'NEUTRAL';              uiColor = 'gray';  }
    res.json({ series, state, uiColor });
  } catch (err: any) {
    res.status(502).json({ error: err.message });
  }
});

app.get('/api/market/breadth', auth, async (req, res) => {
  try {
    const [spyRes, rspRes] = await Promise.all([
      axios.get('https://query1.finance.yahoo.com/v8/finance/chart/SPY?interval=1d&range=2y', { timeout: 10000 }),
      axios.get('https://query1.finance.yahoo.com/v8/finance/chart/RSP?interval=1d&range=2y', { timeout: 10000 }),
    ]);
    const spyResult = spyRes.data?.chart?.result?.[0];
    const rspResult = rspRes.data?.chart?.result?.[0];
    if (!spyResult || !rspResult) { res.status(502).json({ error: 'Missing SPY or RSP data' }); return; }

    const toMap = (result: any): Map<string, number> => {
      const ts: number[]              = result.timestamp ?? [];
      const closes: (number | null)[] = result.indicators?.quote?.[0]?.close ?? [];
      const m = new Map<string, number>();
      ts.forEach((t, i) => { if (closes[i] != null) m.set(new Date(t * 1000).toISOString().slice(0, 10), closes[i]!); });
      return m;
    };

    const rolling200Sma = (values: number[]): (number | null)[] => {
      const sma: (number | null)[] = [];
      const win: number[] = [];
      for (const v of values) {
        win.push(v); if (win.length > 200) win.shift();
        sma.push(win.length === 200 ? Math.round(win.reduce((a, b) => a + b, 0) / 200 * 10000) / 10000 : null);
      }
      return sma;
    };

    const spyMap = toMap(spyResult);
    const rspMap = toMap(rspResult);
    const dates  = [...spyMap.keys()].filter(d => rspMap.has(d)).sort();

    // SPY price + SMA
    const priceValues    = dates.map(d => spyMap.get(d)!);
    const priceSma       = rolling200Sma(priceValues);
    const currentPrice   = priceValues[priceValues.length - 1];
    const currentPriceSma = priceSma[priceSma.length - 1];
    const priceHealth: string = currentPriceSma != null && currentPrice > currentPriceSma ? 'Bullish' : 'Bearish';

    // RSP/SPY breadth ratio + SMA
    const ratioValues    = dates.map(d => rspMap.get(d)! / spyMap.get(d)!);
    const ratioSma       = rolling200Sma(ratioValues);
    const currentAdValue = ratioValues[ratioValues.length - 1];
    const currentAdSma   = ratioSma[ratioSma.length - 1];
    const internalHealth: string = currentAdSma != null && currentAdValue > currentAdSma ? 'Strong' : 'Weak';

    const isDivergent = priceHealth === 'Bullish' && internalHealth === 'Weak';

    let interpretation: string;
    let interpretationColor: string;
    if      (priceHealth === 'Bullish' && internalHealth === 'Strong') { interpretation = 'Confirmatory — broad participation. Safest time to be long.';    interpretationColor = 'green'; }
    else if (priceHealth === 'Bullish' && internalHealth === 'Weak')   { interpretation = 'Divergent — generals leading, soldiers retreating. High risk.';   interpretationColor = 'red';   }
    else if (priceHealth === 'Bearish' && internalHealth === 'Strong') { interpretation = 'Accumulation — price lagging but stocks rising under the hood.'; interpretationColor = 'amber'; }
    else                                                                { interpretation = 'Capitulation — maximum systemic weakness.';                      interpretationColor = 'red';   }

    res.json({
      priceHealth, internalHealth, isDivergent, interpretation, interpretationColor,
      adLine:      dates.map((d, i) => ({ date: d, value: Math.round(ratioValues[i] * 100000) / 100000 })),
      prices:      dates.map((d, i) => ({ date: d, value: priceValues[i] })),
      adLineSma200: dates.map((d, i) => ({ date: d, value: ratioSma[i] })),
      priceSma200:  dates.map((d, i) => ({ date: d, value: priceSma[i] })),
      currentPrice, currentAdValue,
      metrics: { lastPrice: currentPrice, lastAD: currentAdValue },
    });
  } catch (err: any) {
    res.status(502).json({ error: err.message });
  }
});

app.get('/api/market/ratio', auth, async (req, res) => {
  try {
    const [soxxRes, qqqRes] = await Promise.all([
      axios.get('https://query1.finance.yahoo.com/v8/finance/chart/SOXX?interval=1d&range=max', { timeout: 10000 }),
      axios.get('https://query1.finance.yahoo.com/v8/finance/chart/QQQ?interval=1d&range=max',  { timeout: 10000 }),
    ]);
    const soxxResult = soxxRes.data?.chart?.result?.[0];
    const qqqResult  = qqqRes.data?.chart?.result?.[0];
    if (!soxxResult || !qqqResult) { res.status(502).json({ error: 'Missing ticker data' }); return; }

    const toMap = (result: any): Map<string, number> => {
      const ts: number[]          = result.timestamp ?? [];
      const closes: (number|null)[] = result.indicators?.quote?.[0]?.close ?? [];
      const m = new Map<string, number>();
      ts.forEach((t, i) => { if (closes[i] != null) m.set(new Date(t * 1000).toISOString().slice(0, 10), closes[i]!); });
      return m;
    };

    const soxxMap = toMap(soxxResult);
    const qqqMap  = toMap(qqqResult);
    const dates      = [...soxxMap.keys()].filter(d => qqqMap.has(d)).sort();
    const ratioArray = dates.map(d => soxxMap.get(d)! / qqqMap.get(d)!);

    const sma200: (number | null)[] = [];
    const win: number[] = [];
    for (let i = 0; i < ratioArray.length; i++) {
      win.push(ratioArray[i]);
      if (win.length > 200) win.shift();
      if (win.length === 200) {
        const sum = win.reduce((a, b) => a + b, 0);
        sma200.push(Math.round((sum / 200) * 10000) / 10000);
      } else {
        sma200.push(null);
      }
    }

    const lastRatio  = ratioArray[ratioArray.length - 1];
    const lastSma    = sma200[sma200.length - 1];
    const status     = lastRatio > (lastSma ?? 0) ? 'BULLISH' : 'BEARISH';

    // Normalized price series (indexed to 100 at first shared date)
    const soxxBase = soxxMap.get(dates[0])!;
    const qqqBase  = qqqMap.get(dates[0])!;
    const soxxNorm = dates.map(d => Math.round((soxxMap.get(d)! / soxxBase) * 10000) / 100);
    const qqqNorm  = dates.map(d => Math.round((qqqMap.get(d)! / qqqBase)  * 10000) / 100);

    // Slope of ratio over last 7 trading days (linear regression)
    const slopeWindow = ratioArray.slice(-7);
    const slope7dDates = [dates[dates.length - slopeWindow.length], dates[dates.length - 1]];
    const n = slopeWindow.length;
    let sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0;
    for (let i = 0; i < n; i++) { sumX += i; sumY += slopeWindow[i]; sumXY += i * slopeWindow[i]; sumX2 += i * i; }
    const slopeValue = (n * sumXY - sumX * sumY) / (n * sumX2 - sumX * sumX);
    let slopeLabel: string;
    if      (slopeValue > 0.0005)                                       slopeLabel = 'sharp_up';
    else if (slopeValue < -0.0001 && lastRatio < (lastSma ?? Infinity)) slopeLabel = 'divergent_down';
    else if (slopeValue < -0.0005)                                      slopeLabel = 'sharp_down';
    else                                                                 slopeLabel = 'neutral';

    console.log('[Ratio] Last 5 SMA200:', sma200.slice(-5));
    res.json({ dates, ratios: ratioArray, sma200, status, currentRatio: lastRatio, currentSma: lastSma, soxxNorm, qqqNorm, slope7d: slopeValue, slope7dDates, slopeLabel });
  } catch (err: any) {
    res.status(502).json({ error: err.message });
  }
});

app.get('/api/market/ratio-hourly', auth, async (req, res) => {
  try {
    const [soxxRes, qqqRes] = await Promise.all([
      axios.get('https://query1.finance.yahoo.com/v8/finance/chart/SOXX?interval=1h&range=60d', { timeout: 10000 }),
      axios.get('https://query1.finance.yahoo.com/v8/finance/chart/QQQ?interval=1h&range=60d',  { timeout: 10000 }),
    ]);
    const soxxResult = soxxRes.data?.chart?.result?.[0];
    const qqqResult  = qqqRes.data?.chart?.result?.[0];
    if (!soxxResult || !qqqResult) { res.status(502).json({ error: 'Missing ticker data' }); return; }

    const toMap = (result: any): Map<number, number> => {
      const ts: number[]             = result.timestamp ?? [];
      const closes: (number|null)[]  = result.indicators?.quote?.[0]?.close ?? [];
      const m = new Map<number, number>();
      ts.forEach((t, i) => { if (closes[i] != null) m.set(t, closes[i]!); });
      return m;
    };

    const soxxMap = toMap(soxxResult);
    const qqqMap  = toMap(qqqResult);
    const ts      = [...soxxMap.keys()].filter(t => qqqMap.has(t)).sort((a, b) => a - b);
    if (!ts.length) { res.status(502).json({ error: 'No overlapping hourly timestamps' }); return; }

    const ratioArray  = ts.map(t => soxxMap.get(t)! / qqqMap.get(t)!);
    const soxxBase    = soxxMap.get(ts[0])!;
    const qqqBase     = qqqMap.get(ts[0])!;

    // 20-period rolling SMA
    const sma20: (number | null)[] = [];
    const win: number[] = [];
    for (const r of ratioArray) {
      win.push(r);
      if (win.length > 20) win.shift();
      sma20.push(win.length === 20 ? Math.round(win.reduce((a, b) => a + b, 0) / 20 * 10000) / 10000 : null);
    }

    const lastRatio = ratioArray[ratioArray.length - 1];
    const lastSma   = sma20[sma20.length - 1];

    // Slope over last 7 hourly points
    const sw = ratioArray.slice(-7);
    const n  = sw.length;
    let sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0;
    for (let i = 0; i < n; i++) { sumX += i; sumY += sw[i]; sumXY += i * sw[i]; sumX2 += i * i; }
    const slopeValue = (n * sumXY - sumX * sumY) / (n * sumX2 - sumX * sumX);
    let slopeLabel: string;
    if      (slopeValue > 0.0005)                                        slopeLabel = 'sharp_up';
    else if (slopeValue < -0.0001 && lastRatio < (lastSma ?? Infinity))  slopeLabel = 'divergent_down';
    else if (slopeValue < -0.0005)                                       slopeLabel = 'sharp_down';
    else                                                                  slopeLabel = 'neutral';

    res.json(ts.map((t, i) => ({
      date:      new Date(t * 1000).toISOString().slice(0, 16).replace('T', ' '),
      ratio:     Math.round(ratioArray[i] * 100000) / 100000,
      sma20:     sma20[i],
      soxxNorm:  Math.round((soxxMap.get(t)! / soxxBase) * 10000) / 100,
      qqqNorm:   Math.round((qqqMap.get(t)! / qqqBase)   * 10000) / 100,
      ...(i === ts.length - 1 ? { slopeLabel, currentRatio: lastRatio, currentSma: lastSma } : {}),
    })));
  } catch (err: any) {
    res.status(502).json({ error: err.message });
  }
});

app.get('/api/market/heatmap', auth, async (req, res) => {
  try {
    const [spyRes, qqqRes, soxxRes] = await Promise.all([
      axios.get('https://query1.finance.yahoo.com/v8/finance/chart/SPY?interval=1d&range=1y',  { timeout: 10000 }),
      axios.get('https://query1.finance.yahoo.com/v8/finance/chart/QQQ?interval=1d&range=1y',  { timeout: 10000 }),
      axios.get('https://query1.finance.yahoo.com/v8/finance/chart/SOXX?interval=1d&range=1y', { timeout: 10000 }),
    ]);
    const calc = (result: any) => {
      const closes: number[] = (result?.indicators?.quote?.[0]?.close ?? []).filter((c: any) => c != null);
      if (!closes.length) return null;
      const latest  = closes[closes.length - 1];
      const high52w = Math.max(...closes);
      return { pct: ((high52w - latest) / high52w) * 100, latest, high52w };
    };
    res.json({
      spy:  calc(spyRes.data?.chart?.result?.[0]),
      qqq:  calc(qqqRes.data?.chart?.result?.[0]),
      soxx: calc(soxxRes.data?.chart?.result?.[0]),
    });
  } catch (err: any) {
    res.status(502).json({ error: err.message });
  }
});

app.get('/api/market/claims', auth, async (req, res) => {
  try {
    const apiKey = process.env.FRED_API_KEY;
    if (!apiKey) { res.status(503).json({ error: 'FRED_API_KEY not configured' }); return; }
    const url = `https://api.stlouisfed.org/fred/series/observations?series_id=IC4WSA&api_key=${apiKey}&file_type=json&sort_order=desc&limit=104`;
    const response = await axios.get(url, { timeout: 10000 });
    const data = (response.data.observations as any[])
      .map((obs: any) => ({ date: obs.date, value: parseFloat(obs.value) }))
      .filter((d: any) => !isNaN(d.value))
      .reverse();
    if (data.length < 5) { res.status(502).json({ error: 'Insufficient claims data' }); return; }

    const latest       = data[data.length - 1].value;
    const previous     = data[data.length - 2].value;
    const fourWeeksAgo = data[data.length - 5]?.value;

    const isImproving    = latest < fourWeeksAgo;
    const trend          = isImproving ? 'Improving' : 'Worsening';
    const trendColor     = isImproving ? 'green' : 'red';
    const floorStatus    = isImproving
      ? 'Claims Decelerating — Floor Support ✅'
      : 'Claims Rising — Macro Risk ⚠';

    res.json({ data, latest, previous, fourWeeksAgo, trend, trendColor, floorStatus });
  } catch (err: any) {
    res.status(502).json({ error: err.message });
  }
});

interface MarketMetrics {
  soxxQqqRatio:  { value: number; sma200: number | null; status: 'Bullish' | 'Bearish' };
  vixStructure:  { ratio: number; status: 'Complacent' | 'Panic' | 'Neutral' };
  indexHealth:   { avgDistFromHigh: number; spy: number; qqq: number; soxx: number };
  breadth:       { ratio: number; sma200: number | null; status: 'Healthy' | 'Narrow' };
  macroFloor:    { current: number; previous: number; isImproving: boolean };
}

function determinePhase(m: MarketMetrics): { phase: string; score: number; color: string } {
  let score = 0;
  if (m.soxxQqqRatio.status === 'Bullish')      score++;
  if (m.vixStructure.ratio < 1.0)               score++;
  if (m.indexHealth.avgDistFromHigh < 5)        score++;
  if (m.breadth.status === 'Healthy')           score++;
  if (m.macroFloor.isImproving)                 score++;
  if (score >= 4) return { phase: 'PHASE 1 — GREEN',    score, color: 'green'  };
  if (score >= 2) return { phase: 'PHASE 2-3 — WATCH',  score, color: 'yellow' };
  return              { phase: 'PHASE 4 — RED',          score, color: 'red'    };
}

app.get('/api/market/signals', auth, async (req, res) => {
  try {
    const toMap = (result: any): Map<string, number> => {
      const ts: number[]              = result?.timestamp ?? [];
      const closes: (number | null)[] = result?.indicators?.quote?.[0]?.close ?? [];
      const m = new Map<string, number>();
      ts.forEach((t, i) => { if (closes[i] != null) m.set(new Date(t * 1000).toISOString().slice(0, 10), closes[i]!); });
      return m;
    };
    const rolling200 = (vals: number[]): number | null => {
      if (vals.length < 200) return null;
      return vals.slice(-200).reduce((a, b) => a + b, 0) / 200;
    };
    const getCloses = (result: any): number[] =>
      (result?.indicators?.quote?.[0]?.close ?? []).filter((c: any) => c != null);

    const [soxxR, qqqR, spyR, rspR, vixR, vix3mR, claimsR] = await Promise.all([
      axios.get('https://query1.finance.yahoo.com/v8/finance/chart/SOXX?interval=1d&range=max', { timeout: 10000 }),
      axios.get('https://query1.finance.yahoo.com/v8/finance/chart/QQQ?interval=1d&range=max',  { timeout: 10000 }),
      axios.get('https://query1.finance.yahoo.com/v8/finance/chart/SPY?interval=1d&range=1y',   { timeout: 10000 }),
      axios.get('https://query1.finance.yahoo.com/v8/finance/chart/RSP?interval=1d&range=1y',   { timeout: 10000 }),
      axios.get('https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?interval=1wk&range=2y',  { timeout: 10000 }),
      axios.get('https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX3M?interval=1wk&range=2y', { timeout: 10000 }),
      ...(process.env.FRED_API_KEY ? [
        axios.get(`https://api.stlouisfed.org/fred/series/observations?series_id=IC4WSA&api_key=${process.env.FRED_API_KEY}&file_type=json&sort_order=desc&limit=10`, { timeout: 10000 }),
      ] : [Promise.resolve(null)]),
    ]);

    // 1. SOXX/QQQ ratio vs 200 SMA
    const soxxMap = toMap(soxxR.data?.chart?.result?.[0]);
    const qqqMap  = toMap(qqqR.data?.chart?.result?.[0]);
    const ratDates = [...soxxMap.keys()].filter(d => qqqMap.has(d)).sort();
    const ratVals  = ratDates.map(d => soxxMap.get(d)! / qqqMap.get(d)!);
    const ratSma200 = rolling200(ratVals);
    const ratLatest = ratVals[ratVals.length - 1];
    const soxxQqqRatio: MarketMetrics['soxxQqqRatio'] = {
      value: ratLatest, sma200: ratSma200,
      status: ratSma200 != null && ratLatest > ratSma200 ? 'Bullish' : 'Bearish',
    };

    // 2. VIX term structure (VIX / VIX3M)
    const vixMap  = toMap(vixR.data?.chart?.result?.[0]);
    const vix3mMap = toMap(vix3mR.data?.chart?.result?.[0]);
    const vixDates = [...vixMap.keys()].filter(d => vix3mMap.has(d)).sort();
    const lastVixDate = vixDates[vixDates.length - 1];
    const vixRatio = lastVixDate ? vixMap.get(lastVixDate)! / vix3mMap.get(lastVixDate)! : 1;
    const vixStructure: MarketMetrics['vixStructure'] = {
      ratio: vixRatio,
      status: vixRatio > 1.05 ? 'Panic' : vixRatio < 0.85 ? 'Complacent' : 'Neutral',
    };

    // 3. Index health (SPY, QQQ, SOXX — 1y highs)
    const spyCloses  = getCloses(spyR.data?.chart?.result?.[0]);
    const qqqCloses1y = getCloses(qqqR.data?.chart?.result?.[0]).slice(-252);
    const soxxCloses1y = getCloses(soxxR.data?.chart?.result?.[0]).slice(-252);
    const pctFromHigh = (closes: number[]) => {
      const high = Math.max(...closes); const last = closes[closes.length - 1];
      return ((high - last) / high) * 100;
    };
    const spyPct = pctFromHigh(spyCloses);
    const qqqPct = pctFromHigh(qqqCloses1y);
    const soxxPct = pctFromHigh(soxxCloses1y);
    const indexHealth: MarketMetrics['indexHealth'] = {
      avgDistFromHigh: (spyPct + qqqPct + soxxPct) / 3,
      spy: spyPct, qqq: qqqPct, soxx: soxxPct,
    };

    // 4. Breadth (RSP/SPY vs 200 SMA)
    const spyMap1y = toMap(spyR.data?.chart?.result?.[0]);
    const rspMap   = toMap(rspR.data?.chart?.result?.[0]);
    const bDates   = [...spyMap1y.keys()].filter(d => rspMap.has(d)).sort();
    const bVals    = bDates.map(d => rspMap.get(d)! / spyMap1y.get(d)!);
    const bSma200  = rolling200(bVals);
    const bLatest  = bVals[bVals.length - 1];
    const breadth: MarketMetrics['breadth'] = {
      ratio: bLatest, sma200: bSma200,
      status: bSma200 != null && bLatest > bSma200 ? 'Healthy' : 'Narrow',
    };

    // 5. Macro floor (FRED claims)
    let macroFloor: MarketMetrics['macroFloor'] = { current: 0, previous: 0, isImproving: true };
    if (claimsR) {
      const obs = ((claimsR as any).data?.observations ?? [])
        .map((o: any) => parseFloat(o.value)).filter((v: number) => !isNaN(v)).reverse();
      if (obs.length >= 5) {
        macroFloor = { current: obs[obs.length - 1], previous: obs[obs.length - 2], isImproving: obs[obs.length - 1] < obs[obs.length - 5] };
      }
    }

    const metrics: MarketMetrics = { soxxQqqRatio, vixStructure, indexHealth, breadth, macroFloor };
    const { phase, score, color } = determinePhase(metrics);

    const scoreBreakdown = [
      { indicator: 'SOX/QQQ Ratio', scored: soxxQqqRatio.status === 'Bullish',     value: `${soxxQqqRatio.status} — ratio ${ratLatest.toFixed(4)}` },
      { indicator: 'VIX Structure', scored: vixStructure.ratio < 1.0,              value: `${vixStructure.status} — ratio ${vixRatio.toFixed(3)}` },
      { indicator: 'Index Health',  scored: indexHealth.avgDistFromHigh < 5,       value: `Avg ${indexHealth.avgDistFromHigh.toFixed(1)}% from high` },
      { indicator: 'Breadth',       scored: breadth.status === 'Healthy',          value: `${breadth.status} — RSP/SPY ${bLatest.toFixed(4)}` },
      { indicator: 'Macro Floor',   scored: macroFloor.isImproving,                value: macroFloor.current ? `Claims ${macroFloor.isImproving ? 'improving' : 'worsening'} (${Math.round(macroFloor.current).toLocaleString()}K)` : 'No FRED data' },
    ];

    res.json({ phase, score, color, scoreBreakdown, metrics });
  } catch (err: any) {
    res.status(502).json({ error: err.message });
  }
});

app.post('/api/fetch-now', auth, async (req, res) => {
  try {
    const result = await runAllFetchers();
    res.json({ ok: true, ...result });
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

app.post('/api/send-weekly-email', auth, async (req, res) => {
  try {
    await sendWeeklyEmail();
    res.json({ ok: true, message: 'Weekly email sent' });
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

app.get('/api/status', auth, (req, res) => {
  res.json({
    trading212: { connected: !!process.env.T212_API_KEY,     method: 'api-key' },
    kraken:     { connected: !!process.env.KRAKEN_API_KEY,   method: 'api-key' },
    binance:    { connected: !!process.env.BINANCE_API_KEY,  method: 'api-key' },
    revolut_balance: { connected: true, method: 'manual' },
    revolut_stocks:  { connected: true, method: 'manual' },
    revolut_crypto:  { connected: true, method: 'manual' },
    tiger:           { connected: true, method: 'manual' },
    china_bank:      { connected: true, method: 'manual' },
    ctbc_balance:    { connected: true, method: 'manual' },
    ctbc_stocks:     { connected: true, method: 'manual' },
    dbs:             { connected: true, method: 'manual' },
  });
});

app.get('/auth/truelayer/connect', (req, res) => {
  const provider = req.query.provider as 'hsbc' | 'revolut';
  if (!['hsbc', 'revolut'].includes(provider)) { res.status(400).send('provider must be hsbc or revolut'); return; }
  const redirectUri = `${req.protocol}://${req.get('host')}/auth/truelayer/callback`;
  res.redirect(buildAuthUrl(provider, redirectUri));
});

app.get('/auth/truelayer/callback', async (req, res) => {
  const { code, state, error } = req.query;
  if (error) { res.send(`<h2>Auth error: ${error}</h2>`); return; }
  const provider    = state as 'hsbc' | 'revolut';
  const redirectUri = `${req.protocol}://${req.get('host')}/auth/truelayer/callback`;
  try {
    await exchangeCode(code as string, provider, redirectUri);
    res.send(`<html><body style="font-family:system-ui;padding:2rem;max-width:500px;margin:auto">
      <h2 style="color:green">✓ ${provider.toUpperCase()} connected</h2>
      <p>Your ${provider} account is authorised. You can close this tab.</p>
      <p><a href="/">Return to dashboard</a></p>
    </body></html>`);
  } catch (err: any) {
    res.status(500).send(`<h2>Failed: ${err.message}</h2>`);
  }
});

app.use(express.static(path.join(__dirname, '..', 'public')));

app.listen(PORT, () => {
  console.log(`\nAsset Hub running at http://localhost:${PORT}`);
  console.log(`Password: ${process.env.DASHBOARD_PASSWORD}`);
  startScheduler();
});

export default app;
