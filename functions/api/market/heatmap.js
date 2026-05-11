import { withCache, yf, yfetch } from './_shared.js';

export const onRequestGet = async (ctx) => {
  return withCache(ctx, 'heatmap', 21600, async () => {
    const [spyData, qqqData, soxxData] = await Promise.all([
      yfetch(yf('SPY',  '1d', '1y')),
      yfetch(yf('QQQ',  '1d', '1y')),
      yfetch(yf('SOXX', '1d', '1y')),
    ]);
    const calc = (data) => {
      const closes = (data?.chart?.result?.[0]?.indicators?.quote?.[0]?.close ?? []).filter(c => c != null);
      if (!closes.length) return null;
      const latest  = closes[closes.length - 1];
      const high52w = Math.max(...closes);
      return { pct: ((high52w - latest) / high52w) * 100, latest, high52w };
    };
    return { spy: calc(spyData), qqq: calc(qqqData), soxx: calc(soxxData) };
  });
};
