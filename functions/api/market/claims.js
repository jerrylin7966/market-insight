import { withCache, jsonResponse } from './_shared.js';

export const onRequestGet = async (ctx) => {
  const fredKey = ctx.env.FRED_API_KEY;
  if (!fredKey) return jsonResponse({ error: 'FRED_API_KEY not configured' }, 0);

  return withCache(ctx, 'claims', 21600, async () => {
    const url = `https://api.stlouisfed.org/fred/series/observations?series_id=IC4WSA&api_key=${fredKey}&file_type=json&sort_order=desc&limit=104`;
    const r = await fetch(url, { signal: AbortSignal.timeout(10000) });
    if (!r.ok) throw new Error(`FRED ${r.status}`);
    const body = await r.json();

    const data = (body.observations ?? [])
      .map(obs => ({ date: obs.date, value: parseFloat(obs.value) }))
      .filter(d => !isNaN(d.value))
      .reverse();
    if (data.length < 5) throw new Error('Insufficient claims data');

    const latest       = data[data.length - 1].value;
    const previous     = data[data.length - 2].value;
    const fourWeeksAgo = data[data.length - 5]?.value;
    const isImproving  = latest < fourWeeksAgo;

    return {
      data, latest, previous, fourWeeksAgo,
      trend: isImproving ? 'Improving' : 'Worsening',
      trendColor: isImproving ? 'green' : 'red',
      floorStatus: isImproving
        ? 'Claims Decelerating — Floor Support ✅'
        : 'Claims Rising — Macro Risk ⚠',
    };
  });
};
