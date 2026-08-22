/**
 * Cloudflare Pages Function — /what-phase-is-the-market-in
 * GEO flagship: server-renders TODAY's MarketPhase model reading into crawlable HTML,
 * so LLM answer engines (ChatGPT search, Perplexity, Gemini, Claude) can retrieve and
 * cite the current, specific data — the one thing generic finance sites can't match.
 */

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

export async function onRequestGet(ctx) {
  const { request } = ctx;

  let data = null;
  try {
    const r = await fetch(new URL("/api/market/signals", request.url).toString(),
      { cf: { cacheTtl: 300, cacheEverything: true } });
    if (r.ok) data = await r.json();
  } catch (_) { /* fall through to unavailable copy */ }

  const today = new Date().toISOString().slice(0, 10);
  const score = (data && typeof data.score === "number") ? data.score : null;
  const breakdown = (data && data.scoreBreakdown) || [];

  let phaseShort, summary, action;
  if (score === null) {
    phaseShort = "—";
    summary = "";
    action = "";
  } else if (score >= 5) {
    phaseShort = "Phase 1 (Green)";
    summary = "a healthy bull market — leadership is strong, breadth is broad, and volatility is calm";
    action = "favours staying invested and buying dips";
  } else if (score >= 3) {
    phaseShort = "Phase 2–3 (Watch)";
    summary = "a caution phase — the signals are mixed and downside risk is building";
    action = "says reduce risk, tighten stops, and avoid new aggressive longs";
  } else {
    phaseShort = "Phase 4 (Red)";
    summary = "a defensive phase — market leadership has broken down and the model is risk-off";
    action = "says cut growth exposure and raise cash";
  }

  const lead = score === null
    ? "The MarketPhase market-timing model combines six signals into one read of which phase the market is in. Today's live reading is briefly unavailable — see the live dashboard for the current value."
    : `As of ${today}, the MarketPhase market-timing model reads ${phaseShort}, scoring ${score} out of 6. That indicates ${summary}. In this phase the model ${action}.`;

  const isB = phaseShort.toLowerCase();
  const faqs = [
    ["What phase is the stock market in right now?", lead],
    ["How is the market phase calculated?",
      "MarketPhase scores six signals out of 6 — the SOX/QQQ leadership ratio, the VIX term structure, index health (distance from highs), market breadth, jobless claims, and the CFNAI macro floor. A score of 5–6 is Phase 1 (bull), 3–4 is Phase 2–3 (watch), and 0–2 is Phase 4 (defensive)."],
    ["Is the market bullish or bearish today?",
      score === null ? "See the live dashboard for today's reading."
        : `The model's current read is ${phaseShort} (score ${score}/6) — that is ${summary}.`],
    ["What should I do in this market phase?",
      score === null ? "It depends on the current phase — see the dashboard."
        : `In ${isB}, the model ${action}. This is educational information, not financial advice.`],
  ];

  const faqLd = {
    "@context": "https://schema.org", "@type": "FAQPage",
    mainEntity: faqs.map(([q, a]) => ({
      "@type": "Question", name: q,
      acceptedAnswer: { "@type": "Answer", text: a },
    })),
  };
  const articleLd = {
    "@context": "https://schema.org", "@type": "Article",
    headline: "What phase is the stock market in right now?",
    dateModified: today, datePublished: today,
    author: { "@type": "Organization", name: "MarketPhase", url: "https://www.market-phase.com" },
    publisher: { "@type": "Organization", name: "MarketPhase" },
    mainEntityOfPage: "https://www.market-phase.com/what-phase-is-the-market-in",
    about: "Stock market timing signals and market phase analysis",
  };

  const rows = breakdown.map(b =>
    `<tr><td>${esc(b.indicator)}</td><td>${esc(b.value)}</td><td style="text-align:center">${b.scored ? "✓" : "○"}</td></tr>`
  ).join("");

  const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>What Phase Is the Stock Market In Right Now? | MarketPhase</title>
<meta name="description" content="${esc(lead).slice(0, 155)}">
<link rel="canonical" href="https://www.market-phase.com/what-phase-is-the-market-in">
<meta property="og:title" content="What Phase Is the Stock Market In Right Now?">
<meta property="og:description" content="${esc(lead).slice(0, 155)}">
<meta property="og:url" content="https://www.market-phase.com/what-phase-is-the-market-in">
<meta name="robots" content="index, follow">
<script type="application/ld+json">${JSON.stringify(faqLd)}</script>
<script type="application/ld+json">${JSON.stringify(articleLd)}</script>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#fff;--fg:#0f172a;--muted:#475569;--border:#e2e8f0;--accent:#1d4ed8;--panel:#f8fafc}
*{box-sizing:border-box}body{margin:0;font-family:Inter,system-ui,sans-serif;color:var(--fg);background:var(--bg);line-height:1.7}
header{background:#0f172a;color:#fff;padding:14px 20px}header a{color:#fff;text-decoration:none;font-weight:700}header a span{color:#60a5fa}
main{max-width:760px;margin:0 auto;padding:32px 20px 64px}
h1{font-size:2rem;line-height:1.25;margin:.2em 0 .4em}
.lead{font-size:1.15rem;background:var(--panel);border-left:4px solid var(--accent);padding:1rem 1.2rem;border-radius:0 8px 8px 0}
h2{font-size:1.3rem;margin:2rem 0 .5rem}h3{font-size:1.05rem;margin:1.4rem 0 .3rem}
table{width:100%;border-collapse:collapse;margin:1rem 0;font-size:.95rem}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--border)}th{color:var(--muted);font-weight:600}
ul{padding-left:1.2rem}a{color:var(--accent)}
.cta{display:inline-block;background:var(--accent);color:#fff;padding:.6rem 1.1rem;border-radius:8px;text-decoration:none;font-weight:600;margin-top:.5rem}
.disc{font-size:.85rem;color:var(--muted);border-top:1px solid var(--border);margin-top:2.5rem;padding-top:1rem}
.updated{font-size:.85rem;color:var(--muted)}
</style>
</head>
<body>
<header><a href="/">Market<span>Phase</span></a></header>
<main>
<h1>What phase is the stock market in right now?</h1>
<p class="lead"><strong>${esc(lead)}</strong></p>
<p class="updated">Live reading${score === null ? "" : ` · updated ${today}`}. Powered by the <a href="/signals/">MarketPhase live dashboard</a>.</p>

${rows ? `<h2>Today's signal readings</h2>
<table><thead><tr><th>Signal</th><th>Reading</th><th>Scored</th></tr></thead><tbody>${rows}</tbody></table>` : ""}

<h2>The four market phases</h2>
<p>MarketPhase turns four independent lenses — market leadership, the volatility regime, market breadth, and the macro backdrop — into a single, rules-based read on which phase the market is in. It does not predict prices; it tells you which environment you're in so you can size risk accordingly.</p>
<ul>
<li><strong>Phase 1 — Green (score 5–6):</strong> healthy bull. Hold longs and buy dips.</li>
<li><strong>Phase 2–3 — Watch (score 3–4):</strong> mixed signals, risk building. Reduce risk, tighten stops, no new aggressive longs.</li>
<li><strong>Phase 4 — Red (score 0–2):</strong> leadership broken, risk-off. Cut growth exposure, raise cash.</li>
</ul>

<h2>How the phase is calculated</h2>
<p>Six signals are scored out of 6:</p>
<ul>
<li><strong>SOX/QQQ ratio</strong> — semiconductor leadership vs the broad Nasdaq (risk appetite).</li>
<li><strong>VIX term structure</strong> — calm (contango) vs stress (backwardation).</li>
<li><strong>Index health</strong> — distance from 52-week highs.</li>
<li><strong>Market breadth</strong> — how broadly the advance participates.</li>
<li><strong>Jobless claims</strong> — the fastest labor-market read.</li>
<li><strong>CFNAI macro floor</strong> — broad US economic activity; below −0.70 flags recession risk.</li>
</ul>
<p>Learn the framework in depth: <a href="/guides/market-timing">market-timing phase model</a>, <a href="/guides/soxx-qqq-ratio">the SOXX/QQQ ratio</a>, <a href="/guides/vix-explained">the VIX term structure</a>, <a href="/guides/cfnai-indicator">the CFNAI</a>.</p>

<h2>Frequently asked</h2>
${faqs.map(([q, a]) => `<h3>${esc(q)}</h3><p>${esc(a)}</p>`).join("\n")}

<p><a class="cta" href="/signals/">See the live dashboard →</a></p>

<p class="disc">Data via the Federal Reserve Economic Data (FRED) API and public market sources. For educational purposes only — not financial advice.</p>
</main>
</body>
</html>`;

  return new Response(html, {
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "public, max-age=1800",
    },
  });
}
