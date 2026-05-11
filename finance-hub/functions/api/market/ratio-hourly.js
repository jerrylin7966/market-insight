import { yf, yfetch, jsonResponse } from './_shared.js';

export const onRequestGet = async () => {
  const [soxxData, qqqData] = await Promise.all([
    yfetch(yf('SOXX', '1h', '60d')),
    yfetch(yf('QQQ',  '1h', '60d')),
  ]);
  const soxxResult = soxxData?.chart?.result?.[0];
  const qqqResult  = qqqData?.chart?.result?.[0];
  if (!soxxResult || !qqqResult) return jsonResponse({ error: 'Missing ticker data' }, 0);

  const toNumMap = (result) => {
    const ts = result.timestamp ?? [];
    const closes = result.indicators?.quote?.[0]?.close ?? [];
    const m = new Map();
    ts.forEach((t, i) => { if (closes[i] != null) m.set(t, closes[i]); });
    return m;
  };

  const soxxMap    = toNumMap(soxxResult);
  const qqqMap     = toNumMap(qqqResult);
  const timestamps = [...soxxMap.keys()].filter(t => qqqMap.has(t)).sort((a, b) => a - b);
  if (!timestamps.length) return jsonResponse({ error: 'No overlapping hourly timestamps' }, 0);

  const ratioArray = timestamps.map(t => soxxMap.get(t) / qqqMap.get(t));
  const soxxBase   = soxxMap.get(timestamps[0]);
  const qqqBase    = qqqMap.get(timestamps[0]);

  const sma20 = [];
  const win = [];
  for (const r of ratioArray) {
    win.push(r);
    if (win.length > 20) win.shift();
    sma20.push(win.length === 20 ? Math.round(win.reduce((a, b) => a + b, 0) / 20 * 10000) / 10000 : null);
  }

  const lastRatio = ratioArray[ratioArray.length - 1];
  const lastSma   = sma20[sma20.length - 1];
  const sw = ratioArray.slice(-7);
  const n  = sw.length;
  let sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0;
  for (let i = 0; i < n; i++) { sumX += i; sumY += sw[i]; sumXY += i * sw[i]; sumX2 += i * i; }
  const slopeValue = (n * sumXY - sumX * sumY) / (n * sumX2 - sumX * sumX);
  const slopeLabel = slopeValue > 0.0005 ? 'sharp_up'
    : (slopeValue < -0.0001 && lastRatio < (lastSma ?? Infinity)) ? 'divergent_down'
    : slopeValue < -0.0005 ? 'sharp_down' : 'neutral';

  const rows = timestamps.map((t, i) => ({
    date:     new Date(t * 1000).toISOString().slice(0, 16).replace('T', ' '),
    ratio:    Math.round(ratioArray[i] * 100000) / 100000,
    sma20:    sma20[i],
    soxxNorm: Math.round((soxxMap.get(t) / soxxBase) * 10000) / 100,
    qqqNorm:  Math.round((qqqMap.get(t)  / qqqBase)  * 10000) / 100,
    ...(i === timestamps.length - 1 ? { slopeLabel, currentRatio: lastRatio, currentSma: lastSma } : {}),
  }));

  // No long-term cache — hourly data changes frequently
  return jsonResponse(rows, 300);
};
