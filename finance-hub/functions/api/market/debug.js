// Temporary debug endpoint — remove after confirming env vars work
// Visit: /api/market/debug
export const onRequestGet = async (ctx) => {
  const fredKey = ctx.env.FRED_API_KEY;
  const info = {
    hasFredKey: Boolean(fredKey),
    fredKeyLength: fredKey ? fredKey.length : 0,
    fredKeyPrefix: fredKey ? fredKey.slice(0, 4) + '...' : null,
    envKeys: Object.keys(ctx.env || {}),
    timestamp: new Date().toISOString(),
  };
  return new Response(JSON.stringify(info, null, 2), {
    headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
  });
};
