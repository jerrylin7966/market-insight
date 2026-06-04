#!/usr/bin/env python3
"""
Daily Market Digest Generator
Fetches RSS headlines from financial news sources,
calls Claude API to write a styled digest,
then saves to finance-hub/daily/YYYY-MM-DD.html
and updates finance-hub/daily/index.html
"""

import os
import sys
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, date
from pathlib import Path
import urllib.request
import urllib.error
import time


def urlopen_with_retry(req, timeout=90, retries=3, backoff=15):
    """urlopen with automatic retry on timeout or transient network errors."""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except (TimeoutError, urllib.error.URLError) as e:
            last_err = e
            if attempt < retries:
                wait = backoff * attempt
                print(f"  [warn] Request attempt {attempt} failed ({e}), retrying in {wait}s…", file=sys.stderr)
                time.sleep(wait)
    raise RuntimeError(f"Request failed after {retries} attempts: {last_err}")


# ── Config ──────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
REPO_ROOT = Path(__file__).parent.parent
DAILY_DIR = REPO_ROOT / "finance-hub" / "daily"
MAX_HEADLINES = 30   # max headlines to pass to Claude

# RSS feeds — all free, no API key needed
FEEDS = [
    {
        "name": "Yahoo Finance",
        "url": "https://finance.yahoo.com/news/rssindex",
    },
    {
        "name": "Reuters Business",
        "url": "https://feeds.reuters.com/reuters/businessNews",
    },
    {
        "name": "Seeking Alpha Market News",
        "url": "https://seekingalpha.com/market_currents.xml",
    },
    {
        "name": "MarketWatch Top Stories",
        "url": "https://feeds.marketwatch.com/marketwatch/topstories/",
    },
    {
        "name": "CNBC Finance",
        "url": "https://www.cnbc.com/id/10000664/device/rss/rss.html",
    },
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def fetch_feed(feed: dict) -> list[dict]:
    """Fetch and parse a single RSS feed. Returns list of {title, link, summary}."""
    items = []
    try:
        req = urllib.request.Request(
            feed["url"],
            headers={"User-Agent": "Mozilla/5.0 (compatible; MarketPhase-digest/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
        root = ET.fromstring(raw)
        ns = {}
        # Handle both RSS and Atom
        for item in root.iter("item"):
            title_el = item.find("title")
            link_el = item.find("link")
            desc_el = item.find("description")
            title = (title_el.text or "").strip() if title_el is not None else ""
            link = (link_el.text or "").strip() if link_el is not None else ""
            summary = (desc_el.text or "").strip() if desc_el is not None else ""
            # Strip HTML tags from summary
            summary = re.sub(r"<[^>]+>", "", summary)[:300]
            if title:
                items.append({"source": feed["name"], "title": title, "link": link, "summary": summary})
    except Exception as e:
        print(f"  [warn] {feed['name']}: {e}", file=sys.stderr)
    return items


def gather_headlines() -> list[dict]:
    """Fetch all feeds and return deduplicated headline list."""
    all_items = []
    seen_titles = set()
    for feed in FEEDS:
        print(f"  Fetching {feed['name']}…", file=sys.stderr)
        for item in fetch_feed(feed):
            key = item["title"].lower()[:60]
            if key not in seen_titles:
                seen_titles.add(key)
                all_items.append(item)
    return all_items[:MAX_HEADLINES]


def call_claude(headlines: list[dict], today_str: str) -> str:
    """Call Claude API to generate digest HTML sections."""
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set")

    headlines_text = "\n".join(
        f"[{h['source']}] {h['title']}\n  {h['summary']}"
        for h in headlines
    )

    prompt = f"""You are MarketPhase's daily financial markets editor. Today is {today_str}.

Here are today's top financial news headlines:

{headlines_text}

Write a comprehensive daily market digest for individual investors. Structure your response as JSON with these keys:

{{
  "market_summary": "3-4 sentence overview of today's key market themes and what is driving price action",
  "key_stories": [
    {{"headline": "short headline", "analysis": "2-3 sentence plain-English explanation of what happened, why it matters, and what investors should watch next"}},
    ... (pick 5-7 most important stories)
  ],
  "key_numbers": [
    {{"label": "metric name", "value": "number or figure", "context": "one sentence explaining what this number means"}},
    ... (3-4 specific data points from today: index moves, yields, commodity prices, economic figures)
  ],
  "sectors_watch": "3-4 sentences on which sectors are in focus today, which are outperforming and underperforming, and why",
  "macro_note": "3-4 sentences on the macro/economic backdrop — Fed policy, interest rates, inflation, jobs, or global factors",
  "investor_takeaway": "4-5 sentences of original analysis: what today's news means for a long-term individual investor, what risks to watch, and what to monitor in the coming days. Be specific and actionable.",
  "marketphase_take": "3-4 sentences of MarketPhase's editorial perspective on today's market environment. Reference the broader market cycle context. Be direct and opinionated — this is original analysis, not a summary.",
  "market_outlook": "2-3 sentences on the near-term outlook: key events or data releases coming up this week that could move markets"
}}

Write with authority and original insight. Each section must contain substantive analysis, not just summaries. Investors rely on this for genuine understanding of market conditions."""

    def _call_api(max_tok: int, msgs: list) -> dict:
        """Make one API call and return parsed JSON."""
        payload = json.dumps({
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": max_tok,
            "messages": msgs,
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            method="POST",
        )
        with urlopen_with_retry(req, timeout=90) as resp:
            result = json.loads(resp.read())

        # Check if we hit the token limit
        stop_reason = result.get("stop_reason", "")
        if stop_reason == "max_tokens":
            raise ValueError(f"Response truncated (stop_reason=max_tokens, tokens={max_tok})")

        raw = result["content"][0]["text"].strip()
        # Strip markdown fences
        fence = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
        if fence:
            raw = fence.group(1).strip()
        start = raw.find('{')
        if start != -1:
            raw = raw[start:]
        decoder = json.JSONDecoder()
        try:
            obj, _ = decoder.raw_decode(raw)
            return obj
        except json.JSONDecodeError:
            cleaned = re.sub(r',\s*([}\]])', r'\1', raw)
            obj, _ = decoder.raw_decode(cleaned)
            return obj

    msgs = [{"role": "user", "content": prompt}]

    # Try with increasing token budgets before giving up
    for max_tok in [4096, 6000, 8000]:
        try:
            return _call_api(max_tok, msgs)
        except (ValueError, json.JSONDecodeError) as e:
            print(f"  [warn] Claude parse failed at {max_tok} tokens: {e}", file=sys.stderr)
            if max_tok == 8000:
                raise
            continue


def render_html(digest: dict, today: date, headlines: list[dict]) -> str:
    """Render the full HTML page for a digest."""
    date_display = today.strftime("%A, %B %-d, %Y")
    date_iso = today.isoformat()

    stories_html = ""
    for s in digest.get("key_stories", []):
        stories_html += f"""
        <div class="story-card">
          <h3>{s['headline']}</h3>
          <p>{s['analysis']}</p>
        </div>"""

    numbers_html = ""
    for n in digest.get("key_numbers", []):
        numbers_html += f"""
        <div class="number-card">
          <div class="number-label">{n.get('label','')}</div>
          <div class="number-value">{n.get('value','')}</div>
          <div class="number-context">{n.get('context','')}</div>
        </div>"""

    sources_html = ""
    for h in headlines[:12]:
        if h.get("link"):
            sources_html += f'<li><a href="{h["link"]}" target="_blank" rel="noopener nofollow">{h["title"]}</a> <span class="source-tag">{h["source"]}</span></li>\n'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Daily Market Digest — {date_display} | MarketPhase</title>
<meta name="description" content="MarketPhase daily market digest for {date_display}. Key stories, sector watch, and macro notes for investors.">
<link rel="canonical" href="https://www.market-phase.com/daily/{date_iso}.html">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='6' fill='%231d4ed8'/><text x='16' y='23' font-family='Inter,Arial,sans-serif' font-size='20' font-weight='700' text-anchor='middle' fill='white'>M</text></svg>">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<!-- PostHog Analytics -->
<script>!function(t,e){{var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){{function g(t,e){{var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]);t[e]=function(){{t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}}}(p=t.createElement("script")).type="text/javascript",p.crossOrigin="anonymous",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){{var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e}},u.people.toString=function(){{return u.toString(1)+" (stub people)"}},o="init bs ws ge fs capture De calculateEventProperties $s register unregister registerOnce $i opt_in_capturing opt_out_capturing has_opted_in_capturing has_opted_out_capturing clear_opt_in_out_capturing debug identify alias set_config reset people.set people.set_once".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])}},e.__SV=1)}}(document,window.posthog||[]);posthog.init('phc_Dn75vEUONtcBO3kEBaYw7w6xaoHJIHuzIWhEf4kbgpj',{{api_host:'https://us.i.posthog.com',person_profiles:'always'}});posthog.register({{site:'market-phase.com',page_path:window.location.pathname,page_url:window.location.href}});</script>
<script>posthog.capture('digest_viewed',{{date:'{date_iso}'}});</script>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{--bg:#fff;--bg2:#f8fafc;--border:#e2e8f0;--text:#0f172a;--muted:#64748b;--accent:#1d4ed8;--green:#059669;--font:'Inter',system-ui,sans-serif}}
body{{font-family:var(--font);background:var(--bg);color:var(--text);line-height:1.6}}
a{{color:var(--accent)}}
header{{background:#0f172a;color:#fff}}
.nav{{display:flex;align-items:center;justify-content:space-between;padding:0 1.5rem;max-width:1200px;margin:0 auto;height:60px}}
.logo{{font-size:20px;font-weight:700;color:#fff;text-decoration:none}}.logo span{{color:#60a5fa}}
.nav-links{{display:flex;gap:1.5rem}}
.nav-links a{{color:rgba(255,255,255,0.75);text-decoration:none;font-size:14px;font-weight:500}}
.nav-links a:hover{{color:#fff}}
.hero-bar{{background:linear-gradient(135deg,#1e3a5f,#1d4ed8);color:#fff;padding:2.5rem 1.5rem}}
.hero-bar .inner{{max-width:820px;margin:0 auto}}
.hero-bar .label{{font-size:12px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:#93c5fd;margin-bottom:.5rem}}
.hero-bar h1{{font-size:clamp(1.5rem,4vw,2.2rem);font-weight:700;line-height:1.25}}
.hero-bar .date{{font-size:14px;color:rgba(255,255,255,0.7);margin-top:.5rem}}
.content{{max-width:820px;margin:0 auto;padding:2.5rem 1.5rem}}
.section-label{{font-size:11px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--accent);margin-bottom:.75rem}}
.summary-box{{background:var(--bg2);border-left:4px solid var(--accent);padding:1.25rem 1.5rem;border-radius:0 8px 8px 0;margin-bottom:2.5rem;font-size:1.05rem;line-height:1.75;color:#1e293b}}
.stories-grid{{display:grid;gap:1rem;margin-bottom:2.5rem}}
.story-card{{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:1.25rem 1.5rem}}
.story-card h3{{font-size:1rem;font-weight:600;margin-bottom:.4rem;color:var(--text)}}
.story-card p{{font-size:.95rem;color:#334155;line-height:1.65}}
.two-col{{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:2.5rem}}
@media(max-width:600px){{.two-col{{grid-template-columns:1fr}}}}
.info-card{{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:1.25rem 1.5rem}}
.info-card h3{{font-size:.8rem;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);margin-bottom:.6rem}}
.info-card p{{font-size:.95rem;color:#1e293b;line-height:1.65}}
.numbers-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:.75rem;margin-bottom:2.5rem}}
.number-card{{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:1rem 1.25rem;text-align:center}}
.number-label{{font-size:.75rem;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);margin-bottom:.3rem}}
.number-value{{font-size:1.6rem;font-weight:700;color:var(--accent);margin-bottom:.3rem}}
.number-context{{font-size:.8rem;color:#64748b;line-height:1.5}}
.analysis-box{{background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;padding:1.5rem;margin-bottom:1.5rem}}
.analysis-box h3{{font-size:.8rem;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:#065f46;margin-bottom:.75rem}}
.analysis-box p{{font-size:.95rem;color:#1e293b;line-height:1.75}}
.take-box{{background:#fefce8;border:1px solid #fde68a;border-radius:10px;padding:1.5rem;margin-bottom:2.5rem}}
.take-box h3{{font-size:.8rem;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:#92400e;margin-bottom:.75rem}}
.take-box p{{font-size:.95rem;color:#1e293b;line-height:1.75;font-style:italic}}
.sources-section{{margin-bottom:2.5rem}}
.sources-section ul{{list-style:none;display:flex;flex-direction:column;gap:.5rem}}
.sources-section li{{font-size:.9rem}}
.sources-section a{{color:var(--text);text-decoration:none}}
.sources-section a:hover{{color:var(--accent)}}
.source-tag{{font-size:.75rem;color:var(--muted);margin-left:.4rem}}
.disclaimer{{font-size:.8rem;color:var(--muted);border-top:1px solid var(--border);padding-top:1.5rem;margin-bottom:2rem}}
.cta-bar{{background:#eff6ff;border:1px solid #bfdbfe;border-radius:12px;padding:1.25rem 1.5rem;display:flex;align-items:center;justify-content:space-between;gap:1rem;flex-wrap:wrap;margin-bottom:2.5rem}}
.cta-bar p{{font-size:.95rem;color:#1e40af;font-weight:500}}
.cta-bar a{{background:var(--accent);color:#fff;padding:.5rem 1.1rem;border-radius:6px;text-decoration:none;font-size:.9rem;font-weight:600;white-space:nowrap}}
footer{{background:#0f172a;color:rgba(255,255,255,.5);padding:32px 0;margin-top:0;text-align:center;font-size:13px}}
footer a{{color:rgba(255,255,255,.6)}}
</style>
<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-02WMHRBYWL"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments)}}gtag('js',new Date());gtag('config','G-02WMHRBYWL');</script>
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-5264064065432511" crossorigin="anonymous"></script>
</head>
<body>

<header>
  <nav class="nav">
    <a href="/" class="logo">Market<span>Phase</span></a>
    <div class="nav-links">
      <a href="/signals/">Live Signals</a>
      <a href="/guides/">Guides</a>
      <a href="/daily/">Daily Digest</a>
      <a href="/about.html">About</a>
      <a href="/contact.html">Contact</a>
    </div>
  </nav>
</header>

<div class="hero-bar">
  <div class="inner">
    <div class="label">Daily Market Digest</div>
    <h1>What's Moving Markets Today</h1>
    <div class="date">{date_display}</div>
    <div style="font-size:12px;color:rgba(255,255,255,0.5);margin-top:.5rem">By MarketPhase Research</div>
  </div>
</div>

<div class="content">

  <div class="mp-ad" data-ad-type="feed"></div>

  <div class="section-label">Market Summary</div>
  <div class="summary-box">{digest.get('market_summary', '')}</div>

  <div class="section-label">Key Numbers</div>
  <div class="numbers-grid">{numbers_html}
  </div>

  <div class="section-label">Key Stories</div>
  <div class="stories-grid">{stories_html}
  </div>

  <div class="two-col">
    <div class="info-card">
      <h3>Sectors in Focus</h3>
      <p>{digest.get('sectors_watch', '')}</p>
    </div>
    <div class="info-card">
      <h3>Macro Note</h3>
      <p>{digest.get('macro_note', '')}</p>
    </div>
  </div>

  <div class="analysis-box">
    <h3>What This Means For You</h3>
    <p>{digest.get('investor_takeaway', '')}</p>
  </div>

  <div class="take-box">
    <h3>MarketPhase Take</h3>
    <p>{digest.get('marketphase_take', '')}</p>
  </div>

  <div class="info-card" style="margin-bottom:2.5rem">
    <h3>Market Outlook</h3>
    <p>{digest.get('market_outlook', '')}</p>
  </div>

  <div class="cta-bar">
    <p>Track real-time market signals and indicators →</p>
    <a href="/signals/">View Live Dashboard</a>
  </div>

  <div class="mp-ad" data-ad-type="feed"></div>

  <div class="sources-section">
    <div class="section-label">Source Headlines</div>
    <ul>{sources_html}
    </ul>
  </div>

  <p class="disclaimer">MarketPhase digests are produced for informational and educational purposes only. Content reflects editorial analysis based on publicly available data and is not financial advice. Always conduct your own research and consult a qualified financial advisor before making investment decisions.</p>

</div>

<footer>
  <p><a href="/">MarketPhase</a> · <a href="/signals/">Live Signals</a> · <a href="/guides/">Guides</a> · <a href="/daily/">Daily Digest</a> · <a href="/about.html">About</a> · <a href="/contact.html">Contact</a> · <a href="/privacy.html">Privacy Policy</a></p>
  <p style="margin-top:8px;font-size:11px;color:rgba(255,255,255,0.3)">For informational purposes only. Not financial advice. © 2025 MarketPhase.</p>
</footer>

<script src="/js/ads.js"></script>
<script src="/js/mobile-nav.js"></script>
</body>
</html>"""


def update_index(daily_dir: Path):
    """Regenerate finance-hub/daily/index.html from all existing digest files."""
    html_files = sorted(
        [f for f in daily_dir.glob("????-??-??.html")],
        reverse=True
    )

    cards_html = ""
    for f in html_files[:30]:  # show latest 30
        d = date.fromisoformat(f.stem)
        label = d.strftime("%A, %B %-d, %Y")
        cards_html += f"""
    <a href="/daily/{f.name}" class="digest-card">
      <span class="digest-date">{label}</span>
      <span class="digest-arrow">→</span>
    </a>"""

    index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Daily Market Digest Archive | MarketPhase</title>
<meta name="description" content="Daily market digests from MarketPhase. AI-written summaries of the most important financial news each trading day.">
<link rel="canonical" href="https://www.market-phase.com/daily/">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='6' fill='%231d4ed8'/><text x='16' y='23' font-family='Inter,Arial,sans-serif' font-size='20' font-weight='700' text-anchor='middle' fill='white'>M</text></svg>">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<!-- PostHog Analytics -->
<script>!function(t,e){{var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){{function g(t,e){{var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]);t[e]=function(){{t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}}}(p=t.createElement("script")).type="text/javascript",p.crossOrigin="anonymous",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){{var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e}},u.people.toString=function(){{return u.toString(1)+" (stub people)"}},o="init bs ws ge fs capture De calculateEventProperties $s register unregister registerOnce $i opt_in_capturing opt_out_capturing has_opted_in_capturing has_opted_out_capturing clear_opt_in_out_capturing debug identify alias set_config reset people.set people.set_once".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])}},e.__SV=1)}}(document,window.posthog||[]);posthog.init('phc_Dn75vEUONtcBO3kEBaYw7w6xaoHJIHuzIWhEf4kbgpj',{{api_host:'https://us.i.posthog.com',person_profiles:'always'}});posthog.register({{site:'market-phase.com',page_path:window.location.pathname,page_url:window.location.href}});</script>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{--bg:#fff;--bg2:#f8fafc;--border:#e2e8f0;--text:#0f172a;--muted:#64748b;--accent:#1d4ed8;--font:'Inter',system-ui,sans-serif}}
body{{font-family:var(--font);background:var(--bg);color:var(--text);line-height:1.6}}
a{{color:var(--accent)}}
header{{background:#0f172a;color:#fff}}
.nav{{display:flex;align-items:center;justify-content:space-between;padding:0 1.5rem;max-width:1200px;margin:0 auto;height:60px}}
.logo{{font-size:20px;font-weight:700;color:#fff;text-decoration:none}}.logo span{{color:#60a5fa}}
.nav-links{{display:flex;gap:1.5rem}}
.nav-links a{{color:rgba(255,255,255,0.75);text-decoration:none;font-size:14px;font-weight:500}}
.nav-links a:hover{{color:#fff}}
.page-hero{{background:#0f172a;padding:3rem 1.5rem;text-align:center;color:#fff}}
.page-hero h1{{font-size:clamp(1.6rem,4vw,2.4rem);font-weight:700}}
.page-hero p{{font-size:1rem;color:rgba(255,255,255,.65);margin-top:.75rem;max-width:500px;margin-left:auto;margin-right:auto}}
.content{{max-width:640px;margin:0 auto;padding:2.5rem 1.5rem}}
.digest-list{{display:flex;flex-direction:column;gap:.75rem}}
.digest-card{{display:flex;align-items:center;justify-content:space-between;background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:1rem 1.25rem;text-decoration:none;color:var(--text);transition:border-color .15s,box-shadow .15s}}
.digest-card:hover{{border-color:var(--accent);box-shadow:0 2px 8px rgba(29,78,216,.1)}}
.digest-date{{font-size:.95rem;font-weight:500}}
.digest-arrow{{color:var(--muted);font-size:1.1rem}}
.empty{{text-align:center;color:var(--muted);padding:3rem 0;font-size:.95rem}}
footer{{background:#0f172a;color:rgba(255,255,255,.5);padding:32px 0;margin-top:3rem;text-align:center;font-size:13px}}
footer a{{color:rgba(255,255,255,.6)}}
</style>
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-5264064065432511" crossorigin="anonymous"></script>
</head>
<body>

<header>
  <nav class="nav">
    <a href="/" class="logo">Market<span>Phase</span></a>
    <div class="nav-links">
      <a href="/signals/">Live Signals</a>
      <a href="/guides/">Guides</a>
      <a href="/daily/">Daily Digest</a>
    </div>
  </nav>
</header>

<div class="page-hero">
  <h1>Daily Market Digest</h1>
  <p>AI-written summaries of what's moving markets, published each trading morning.</p>
</div>

<div class="content">
  <div class="digest-list">
    {"<p class='empty'>No digests published yet. Check back tomorrow.</p>" if not cards_html else cards_html}
  </div>
</div>

<footer>
  <p><a href="/">MarketPhase</a> · <a href="/signals/">Live Signals</a> · <a href="/guides/">Guides</a> · <a href="/daily/">Daily Digest</a> · <a href="/about.html">About</a> · <a href="/contact.html">Contact</a> · <a href="/privacy.html">Privacy Policy</a></p>
  <p style="margin-top:8px;font-size:11px;color:rgba(255,255,255,0.3)">For informational purposes only. Not financial advice. © 2025 MarketPhase.</p>
</footer>
<script src="/js/ads.js"></script>
<script src="/js/mobile-nav.js"></script>
</body>
</html>"""

    (daily_dir / "index.html").write_text(index_html, encoding="utf-8")
    print(f"  Updated index.html ({len(html_files)} digest(s) listed)", file=sys.stderr)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    today = date.today()
    date_display = today.strftime("%A, %B %-d, %Y")
    print(f"=== Daily Digest Generator — {date_display} ===", file=sys.stderr)

    DAILY_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Fetch headlines
    print("Fetching RSS feeds…", file=sys.stderr)
    headlines = gather_headlines()
    print(f"  Got {len(headlines)} unique headlines", file=sys.stderr)

    if not headlines:
        print("ERROR: No headlines fetched. Aborting.", file=sys.stderr)
        sys.exit(1)

    # 2. Call Claude
    print("Calling Claude API…", file=sys.stderr)
    digest = call_claude(headlines, date_display)
    print("  Got digest from Claude", file=sys.stderr)

    # 3. Render HTML
    html = render_html(digest, today, headlines)

    # 4. Write daily file
    out_file = DAILY_DIR / f"{today.isoformat()}.html"
    out_file.write_text(html, encoding="utf-8")
    print(f"  Wrote {out_file}", file=sys.stderr)

    # 5. Update index
    print("Updating index.html…", file=sys.stderr)
    update_index(DAILY_DIR)

    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
