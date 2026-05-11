import { toMap, withCache, yf, yfetch, jsonResponse } from './_shared.js';

export const onRequestGet = async (ctx) => {
  return withCache(ctx, 'vix', 21600, async () => {
    const [vixData, vxvData] = await Promise.all([
      yfetch(yf('^VIX',   '1wk', '2y')),
      yfetch(yf('^VIX3M', '1wk', '2y')),
    ]);
    const vixResult = vixData?.chart?.result?.[0];
    const vxvResult = vxvData?.chart?.result?.[0];
    if (!vixResult || !vxvResult) return { error: 'Yahoo Finance data unavailable', series: [] };

    const vixMap = toMap(vixResult);
    const vxvMap = toMap(vxvResult);
    const dates  = [...vixMap.keys()].filter(d => vxvMap.has(d)).sort();
    const series = dates.map(d => ({
      date: d,
      vix:   vixMap.get(d),
      vxv:   vxvMap.get(d),
      ratio: vixMap.get(d) / vxvMap.get(d),
    }));
    const lastRatio = series[series.length - 1]?.ratio ?? 1;
    const state   = lastRatio < 0.85 ? 'EXTREME COMPLACENCY' : lastRatio > 1.05 ? 'PANIC / OPPORTUNITY' : 'NEUTRAL';
    const uiColor = lastRatio < 0.85 ? 'red'                : lastRatio > 1.05 ? 'green'               : 'gray';
    return { series, state, uiColor };
  });
};
