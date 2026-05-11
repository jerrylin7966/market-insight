// Shared helpers for Cloudflare Pages Functions

export function toMap(result) {
  const ts = result?.timestamp ?? [];
  const closes = result?.indicators?.quote?.[0]?.close ?? [];
  const m = new Map();
  ts.forEach((t, i) => {
    if (closes[i] != null) m.set(new Date(t * 1000).toISOString().slice(0, 10), closes[i]);
  });
  return m;
}

export function rolling200(vals) {
  if (vals.length < 200) return null;
  return vals.slice(-200).reduce((a, b) => a + b, 0) / 200;
}

export function rollingArray(vals, period) {
  const sma = [];
  const win = [];
  for (const v of vals) {
    win.push(v);
    if (win.length > period) win.shift();
    sma.push(win.length === period ? Math.round(win.reduce((a, b) => a + b, 0) / period * 10000) / 10000 : null);
  }
  return sma;
}

export function rolling200Array(vals) { return rollingArray(vals, 200); }

export function jsonResponse(data, ttlSeconds = 21600) {
  return new Response(JSON.stringify(data), {
    headers: {
      'Content-Type': 'application/json',
      'Access-Control-Allow-Origin': '*',
      'Cache-Control': `public, max-age=${ttlSeconds}`,
    },
  });
}

export async function withCache(ctx, cacheKey, ttlSeconds, compute) {
  const cache = caches.default;
  const req = new Request(`https://cache.market-insight.internal/${cacheKey}`);
  try {
    const cached = await cache.match(req);
    if (cached) return cached;
  } catch { /* cache unavailable — skip */ }
  try {
    const data = await compute();
    const res = jsonResponse(data, ttlSeconds);
    try { ctx.waitUntil(cache.put(req, res.clone())); } catch { /* ignore cache write errors */ }
    return res;
  } catch (err) {
    return jsonResponse({ error: String(err?.message || err) }, 0);
  }
}

// Yahoo Finance — try query2 first (less blocked), fall back to query1
export function yf(ticker, interval, range) {
  return `https://query2.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(ticker)}?interval=${interval}&range=${range}`;
}

const YF_HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
  'Accept': 'application/json, text/plain, */*',
  'Accept-Language': 'en-US,en;q=0.9',
  'Referer': 'https://finance.yahoo.com/',
  'Origin': 'https://finance.yahoo.com',
};

export async function yfetch(url) {
  try {
    const r = await fetch(url, { headers: YF_HEADERS, signal: AbortSignal.timeout(12000) });
    if (!r.ok) {
      // query2 failed — try query1 as fallback
      const url1 = url.replace('query2.finance.yahoo.com', 'query1.finance.yahoo.com');
      const r1 = await fetch(url1, { headers: YF_HEADERS, signal: AbortSignal.timeout(12000) });
      if (!r1.ok) return null;
      return r1.json();
    }
    return r.json();
  } catch {
    return null;
  }
}
