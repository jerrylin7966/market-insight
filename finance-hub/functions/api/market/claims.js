import { withCache, jsonResponse } from './_shared.js';

const HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
  'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
  'Referer': 'https://fred.stlouisfed.org/',
};

function parseCSV(text) {
  const lines = text.trim().split('\n');
  // Skip header row (DATE,VALUE)
  return lines.slice(1)
    .map(line => {
      const [date, val] = line.split(',');
      const value = parseFloat(val);
      return (!date || isNaN(value)) ? null : { date: date.trim(), value };
    })
    .filter(Boolean);
}

export const onRequestGet = async (ctx) => {
  return withCache(ctx, 'claims-v2', 21600, async () => {
    // Use FRED's public CSV endpoint — avoids the Cloudflare-to-Cloudflare 520 block
    const url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=IC4WSA';
    const r = await fetch(url, { headers: HEADERS, signal: AbortSignal.timeout(15000) });
    if (!r.ok) throw new Error(`FRED CSV ${r.status}`);

    const text = await r.text();
    const all  = parseCSV(text);
    const data = all.slice(-104); // last 2 years
    if (data.length < 5) throw new Error('Insufficient claims data');

    const latest       = data[data.length - 1].value;
    const previous     = data[data.length - 2].value;
    const fourWeeksAgo = data[data.length - 5].value;
    const isImproving  = latest < fourWeeksAgo;

    return {
      data, latest, previous, fourWeeksAgo,
      trend:       isImproving ? 'Improving'  : 'Worsening',
      trendColor:  isImproving ? 'green'       : 'red',
      floorStatus: isImproving
        ? 'Claims Decelerating — Floor Support ✅'
        : 'Claims Rising — Macro Risk ⚠',
    };
  });
};
