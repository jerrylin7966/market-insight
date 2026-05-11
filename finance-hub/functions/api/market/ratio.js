import { toMap, rolling200Array, withCache, yf, yfetch } from './_shared.js';

export const onRequestGet = async (ctx) => {
  return withCache(ctx, 'ratio', 21600, async () => {
    const [soxxData, qqqData] = await Promise.all([
      yfetch(yf('SOXX', '1d', 'max')),
      yfetch(yf('QQQ',  '1d', 'max')),
    ]);
    const soxxResult = soxxData?.chart?.result?.[0];
    const qqqResult  = qqqData?.chart?.result?.[0];
    if (!soxxResult || !qqqResult) return { error: 'Yahoo Finance data unavailable', dates: [], ratios: [], sma200: [] };

    const soxxMap = toMap(soxxResult);
    const qqqMap  = toMap(qqqResult);
    const dates      = [...soxxMap.keys()].filter(d => qqqMap.has(d)).sort();
    const ratioArray = dates.map(d => soxxMap.get(d) / qqqMap.get(d));
    const sma200     = rolling200Array(ratioArray);

    const lastRatio = ratioArray[ratioArray.length - 1];
    const lastSma   = sma200[sma200.length - 1];
    const status    = lastRatio > (lastSma ?? 0) ? 'BULLISH' : 'BEARISH';

    const soxxBase = soxxMap.get(dates[0]);
    const qqqBase  = qqqMap.get(dates[0]);
    const soxxNorm = dates.map(d => Math.round((soxxMap.get(d) / soxxBase) * 10000) / 100);
    const qqqNorm  = dates.map(d => Math.round((qqqMap.get(d)  / qqqBase)  * 10000) / 100);

    const sw = ratioArray.slice(-7);
    const n  = sw.length;
    let sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0;
    for (let i = 0; i < n; i++) { sumX += i; sumY += sw[i]; sumXY += i * sw[i]; sumX2 += i * i; }
    const slopeValue = (n * sumXY - sumX * sumY) / (n * sumX2 - sumX * sumX);
    const slopeLabel = slopeValue > 0.0005 ? 'sharp_up'
      : (slopeValue < -0.0001 && lastRatio < (lastSma ?? Infinity)) ? 'divergent_down'
      : slopeValue < -0.0005 ? 'sharp_down' : 'neutral';

    return { dates, ratios: ratioArray, sma200, status, currentRatio: lastRatio, currentSma: lastSma, soxxNorm, qqqNorm, slope7d: slopeValue, slopeLabel };
  });
};
