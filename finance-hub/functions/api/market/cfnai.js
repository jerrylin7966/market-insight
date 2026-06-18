import { withCache, jsonResponse } from './_shared.js';

async function fetchSeries(seriesId, fredKey) {
  const url = `https://api.stlouisfed.org/fred/series/observations`
    + `?series_id=${seriesId}&api_key=${fredKey}&file_type=json`
    + `&sort_order=asc&observation_start=2000-01-01`;
  const r = await fetch(url, { signal: AbortSignal.timeout(15000) });
  if (!r.ok) throw new Error(`FRED API ${seriesId} ${r.status}`);
  const body = await r.json();
  return (body.observations ?? [])
    .map(obs => ({ date: obs.date.slice(0, 7), value: parseFloat(obs.value) }))
    .filter(d => !isNaN(d.value));
}

function computeMA3(rawSeries) {
  return rawSeries.slice(2).map((_, i) => ({
    date:  rawSeries[i + 2].date,
    value: +((rawSeries[i].value + rawSeries[i+1].value + rawSeries[i+2].value) / 3).toFixed(4),
  }));
}

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

export const onRequestGet = async (ctx) => {
  const fredKey = ctx.env.FRED_API_KEY;
  if (!fredKey) return jsonResponse({ error: 'FRED_API_KEY not configured' }, 0);

  return withCache(ctx, 'cfnai-v7', 21600, async () => {
    const rawSeries = await fetchSeries('CFNAI', fredKey);
    if (!rawSeries.length) throw new Error('No CFNAI data from FRED API');

    let ma3Series;
    try {
      const parsed = await fetchSeries('CFNAIMA3', fredKey);
      ma3Series = parsed.length ? parsed : computeMA3(rawSeries);
    } catch {
      ma3Series = computeMA3(rawSeries);
    }

    if (!ma3Series.length) throw new Error('Could not build CFNAI MA3 series');

    const result = analyseCfnai(ma3Series, rawSeries);
    return { ...result, scored: result.isBullish, source: 'FRED (CFNAI)', fetchedAt: new Date().toISOString() };
  });
};
