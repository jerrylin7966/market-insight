import { withCache, jsonResponse } from './_shared.js';

const HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
  'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
  'Referer': 'https://fred.stlouisfed.org/',
};

function parseCSV(text, truncateToMonth = false) {
  const lines = text.trim().split('\n');
  return lines.slice(1)
    .map(line => {
      const [date, val] = line.split(',');
      const value = parseFloat(val);
      if (!date || isNaN(value)) return null;
      return { date: truncateToMonth ? date.trim().slice(0, 7) : date.trim(), value };
    })
    .filter(Boolean);
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

async function fetchCSV(seriesId) {
  const url = `https://fred.stlouisfed.org/graph/fredgraph.csv?id=${seriesId}`;
  const r = await fetch(url, { headers: HEADERS, signal: AbortSignal.timeout(15000) });
  if (!r.ok) throw new Error(`FRED CSV ${seriesId} ${r.status}`);
  return r.text();
}

export const onRequestGet = async (ctx) => {
  return withCache(ctx, 'cfnai-v4', 21600, async () => {
    const [ma3Text, rawText] = await Promise.all([
      fetchCSV('CFNAIMA3'),
      fetchCSV('CFNAI'),
    ]);

    const ma3Series = parseCSV(ma3Text, true);
    const rawSeries = parseCSV(rawText, true);

    if (!ma3Series.length) throw new Error('No CFNAI data from FRED CSV');

    const result = analyseCfnai(ma3Series, rawSeries);
    return { ...result, scored: result.isBullish, source: 'FRED (CFNAI)', fetchedAt: new Date().toISOString() };
  });
};
