#!/usr/bin/env python3
"""
Daily Market Video Generator
1. Reads today's digest for the top story/theme
2. Calls Claude to write a "Tech Me Home / MarketPhase" style script
   AND structured slide data (bullets + Pexels keywords)
3. Sends narration to ElevenLabs (user's custom voice)
4. Fetches Pexels background images per slide
5. Renders slides: image bg + dark overlay + bullet points
6. Combines slides + audio into MP4 with ffmpeg
7. Uploads to YouTube with description including market-phase.com
"""

import os, sys, re, json, time, subprocess, textwrap, shutil, random
from datetime import date
from pathlib import Path
import urllib.request, urllib.parse, urllib.error


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

# ── Config ───────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY      = os.environ.get("ANTHROPIC_API_KEY", "")
ELEVENLABS_API_KEY     = os.environ.get("ELEVENLABS_API_KEY", "")
PEXELS_API_KEY         = os.environ.get("PEXELS_API_KEY", "")
PIXABAY_API_KEY        = os.environ.get("PIXABAY_API_KEY", "")
YOUTUBE_CLIENT_ID      = os.environ.get("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET  = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
YOUTUBE_REFRESH_TOKEN  = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")

REPO_ROOT  = Path(__file__).parent.parent
DAILY_DIR  = REPO_ROOT / "daily_data"   # private digest cache (not deployed); read for the video/signals script only
TMP_DIR    = Path("/tmp/marketphase_video")

ELEVENLABS_VOICE_ID = "G17SuINrv2H9FC6nvetn"
# Voice model. Default eleven_multilingual_v2 (moved back from eleven_v3).
# Override via ELEVENLABS_MODEL env (e.g. eleven_v3); any model error auto-falls-back
# to multilingual_v2 mid-run so a hiccup never breaks the daily upload.
ELEVENLABS_MODEL          = os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2")
ELEVENLABS_FALLBACK_MODEL = "eleven_multilingual_v2"
SITE_URL   = "https://market-phase.com/"
CLIPS_DIR  = Path(__file__).parent / "assets" / "clips"

SLIDE_W, SLIDE_H = 1920, 1080


# ── Helpers ───────────────────────────────────────────────────────────────────

def install(pkg):
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"],
                          stdout=subprocess.DEVNULL)


def ensure_deps():
    try:
        import PIL
    except ImportError:
        install("Pillow")
    try:
        import numpy
    except ImportError:
        install("numpy")
    try:
        import requests
    except ImportError:
        install("requests")
    # Captions (best-effort): a failed install must NOT break the run —
    # transcribe_words() degrades to "no captions" if faster-whisper is absent.
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        try:
            install("faster-whisper")
        except Exception as e:
            print(f"  faster-whisper install failed ({e}); captions will be skipped",
                  file=sys.stderr)


def read_today_digest() -> str:
    today = date.today().isoformat()
    digest_file = DAILY_DIR / f"{today}.html"
    if not digest_file.exists():
        from datetime import timedelta
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        digest_file = DAILY_DIR / f"{yesterday}.html"
    if not digest_file.exists():
        return "Global markets face uncertainty as inflation pressures persist and central banks signal caution."
    html = digest_file.read_text(encoding="utf-8")
    texts = re.findall(r'class="(?:summary-box|story-card)[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
    clean = " ".join(re.sub(r"<[^>]+>", "", t).strip() for t in texts)
    return clean[:2000] if clean else "Markets navigating turbulent macro conditions."


_HEADLINE_FEEDS = [
    "https://finance.yahoo.com/news/rssindex",
    "https://feeds.reuters.com/reuters/businessNews",
    "https://seekingalpha.com/market_currents.xml",
    "https://feeds.marketwatch.com/marketwatch/topstories/",
    "https://www.cnbc.com/id/10000664/device/rss/rss.html",
]


def fetch_hot_headlines(limit: int = 25):
    """Fresh, entity-rich RSS headlines for picking a SPECIFIC dramatic story
    (named company/person/asset). Best-effort — returns [] on failure so the
    caller falls back to the digest summary. Data shows specific-entity stories
    massively out-reach generic 'market' takes."""
    import xml.etree.ElementTree as ET
    titles, seen = [], set()
    for url in _HEADLINE_FEEDS:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 (compatible; MarketPhase/1.0)"})
            with urllib.request.urlopen(req, timeout=10) as resp:  # fail-fast, best-effort
                root = ET.fromstring(resp.read())
            for item in root.iter("item"):
                t = item.find("title")
                t = (t.text or "").strip() if t is not None else ""
                k = t.lower()[:60]
                if t and k not in seen:
                    seen.add(k); titles.append(t)
        except Exception as e:
            host = url.split("/")[2] if "/" in url else url
            print(f"  [headlines] {host}: {e}", file=sys.stderr)
    print(f"  [headlines] {len(titles)} fetched", file=sys.stderr)
    return titles[:limit]


# ── Claude: generate script + slide data ─────────────────────────────────────

def call_claude_topic(topic: str, today_display: str) -> dict:
    """Generate a video script on a specific topic (on-demand, not from digest)."""
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set")

    prompt = f"""You are a YouTube scriptwriter for "Tech Me Home", a financial education channel by MarketPhase.
Today is {today_display}. The requested video topic is: {topic}

Output a JSON object with exactly these six keys:

1. "title": A catchy YouTube title (max 90 characters) specific to this topic.
   Hook-driven — make viewers feel they MUST click.
   Examples: "The Hidden Truth About {topic}", "Why {topic} Changes Everything"
   No hashtags, no emojis.

2. "short_title": A YouTube Shorts title (max 60 characters). Punchy, no hashtags.

3. "short_hook": A 45-second spoken script (≈100 words) for a YouTube Short.
   CRITICAL RULES — follow exactly:
   - Word 1 must be a shocking statement or number. No intro, no name, no "hey". Start mid-thought.
     Examples: "The Fed just lied to you." / "$39 trillion. That's the hole America is in." / "China just won."
   - Second sentence must make the viewer feel stupid for not knowing this already.
   - Middle: one punchy ELI5 analogy — explain the complex idea like the viewer is 12 years old.
   - End with: "Watch the full breakdown — link in bio." (spoken, not written)
   - Tone: urgent, slightly conspiratorial, like you're telling a secret.
   - No cues, no sponsor, no filler. Pure spoken words only. Every word earns its place.

4. "chapters": Array of chapter objects.
   [{{"time": "0:00", "label": "Intro"}}, {{"time": "0:45", "label": "Topic Name"}}, ...]
   6-8 chapters, labels are 3-5 words, SEO-friendly.

5. "tags": Array of 8-10 tags (no # prefix). Always include "finance", "markets", "investing". Add topic-specific tags.

6. "narration": A full ~8-10 minute spoken script. Rules:
   - INTRO: High-stakes hook (0:00-1:00). After hook: "Welcome back to Tech Me Home, Market Phase daily news!"
   - TONE: Urgent, cinematic, educational. Slightly cynical about the Federal Reserve.
   - SENTENCES: Short, punchy, conversational.
   - CUES: Include [Visual:], [B-Roll:], [Sound effect:], [Graphic:] cues throughout.
   - ELI5: Explain one complex concept with a simple analogy.
   - SPONSOR: At ~2 min, 30-sec [SPONSOR] pitch framed as "protect yourself".
   - OUTRO: Slightly optimistic. End with: "None of this is financial advice, purely for entertainment, always do your own research..."
   - LENGTH: ~900 words.

7. "slides": Array of 8-10 slide objects:
   {{
     "title": "SHORT SLIDE TITLE IN CAPS",
     "bullets": ["Bullet 1", "Bullet 2", "Bullet 3"],
     "clip_tag": "tag_from_library_or_null",
     "pexels_keyword": "fallback image search term",
     "narration_text": "Exact spoken words for this slide"
   }}
   clip_tag options: stock_bull, stock_crash, federal_reserve, wall_street, inflation, gold,
   crypto, oil_energy, recession, interest_rates, global_economy, tech_stocks, jobs, bonds,
   consumer, earnings, nyse_open, dollar, bear_market, data_screens, housing_market, banking,
   china_trade, us_debt, ai_stocks, commodities, retail_earnings, ipo, supply_chain, mergers,
   election_market, healthcare_costs.
   Use null if none fit — pexels_keyword will fetch a royalty-free image instead.
   Every word from narration must appear in exactly one slide's narration_text.

Return ONLY valid JSON. No markdown, no explanation."""

    payload = json.dumps({{
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 8000,
        "messages": [{{"role": "user", "content": prompt}}],
    }}).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={{
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }},
        method="POST",
    )
    with urlopen_with_retry(req, timeout=90) as resp:
        result = json.loads(resp.read())

    raw = result["content"][0]["text"].strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
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


def call_claude_from_script(narration: str, today_display: str) -> dict:
    """Generate metadata + slides from a pre-written narration script (verbatim)."""
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set")

    prompt = f"""You are a YouTube producer for "Tech Me Home", a financial education channel by MarketPhase.
Today is {today_display}. A pre-written narration script has been provided below.
Your job is to generate the video metadata and slide breakdown — do NOT rewrite the narration.

PRE-WRITTEN NARRATION SCRIPT:
\"\"\"
{narration}
\"\"\"

Output a JSON object with exactly these keys:

1. "title": A catchy YouTube title (max 90 characters) derived from this script. Hook-driven. No hashtags, no emojis.

2. "short_title": A YouTube Shorts title (max 60 characters). Punchy, no hashtags.

3. "short_hook": A 45-second spoken script (≈100 words) for a YouTube Short.
   CRITICAL RULES — follow exactly:
   - Word 1 must be a shocking statement or number from the script. No intro, no name, no "hey". Start mid-thought.
     Examples: "The Fed just lied to you." / "$39 trillion. That's the hole America is in." / "China just won."
   - Second sentence must make the viewer feel stupid for not knowing this already.
   - Middle: one punchy ELI5 analogy — explain the complex idea like the viewer is 12 years old.
   - End with: "Watch the full breakdown — link in bio." (spoken, not written)
   - Tone: urgent, slightly conspiratorial, like you're telling a secret.
   - No cues, no sponsor, no filler. Pure spoken words only. Every word earns its place.

4. "chapters": Array of chapter objects matching the script's structure.
   [{{"time": "0:00", "label": "Intro"}}, {{"time": "0:45", "label": "Label Here"}}, ...]
   6-8 chapters, labels are 3-5 words, SEO-friendly.

5. "tags": Array of 8-10 tags (no # prefix). Always include "finance", "markets", "investing". Add topic-specific tags from the script.

6. "narration": Copy the ENTIRE pre-written narration script here VERBATIM — do not change a single word.

7. "slides": Array of 8-10 slide objects aligned to sections of the narration:
   {{
     "title": "SHORT SLIDE TITLE IN CAPS",
     "bullets": ["Bullet 1", "Bullet 2", "Bullet 3"],
     "clip_tag": "tag_from_library_or_null",
     "pexels_keyword": "fallback image search term",
     "narration_text": "Exact portion of the narration for this slide"
   }}
   clip_tag options: stock_bull, stock_crash, federal_reserve, wall_street, inflation, gold,
   crypto, oil_energy, recession, interest_rates, global_economy, tech_stocks, jobs, bonds,
   consumer, earnings, nyse_open, dollar, bear_market, data_screens, housing_market, banking,
   china_trade, us_debt, ai_stocks, commodities, retail_earnings, ipo, supply_chain, mergers,
   election_market, healthcare_costs.
   Use null if none fit — pexels_keyword will fetch a royalty-free image.
   Every word from the narration must appear in exactly one slide's narration_text.

Return ONLY valid JSON. No markdown, no explanation."""

    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 8000,
        "messages": [{"role": "user", "content": prompt}],
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
    with urllib.request.urlopen(req, timeout=90) as resp:
        result = json.loads(resp.read())

    raw = result["content"][0]["text"].strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
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


def call_claude(digest_summary: str, today_display: str) -> dict:
    """Returns dict with 'narration' (full script) and 'slides' (list of slide dicts)."""
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set")

    prompt = f"""You are a YouTube scriptwriter for "Tech Me Home", a financial channel covering MarketPhase daily news.
Today is {today_display}. Today's market summary:

{digest_summary}

Output a JSON object with exactly these six keys:

1. "title": A single catchy YouTube video title (max 90 characters) specific to today's top story. Rules:
   - Must reflect the actual news, not a generic placeholder
   - Hook-driven — make viewers feel they MUST click (fear of missing out, shocking revelation, hidden truth)
   - Examples of good style: "The Fed Just Admitted They Have No Plan", "Why Your 401k Is About To Get Crushed", "This Hidden Signal Predicted Every Crash — It Just Fired Again", "Markets Are Lying To You Right Now"
   - Do NOT use "They're Not Telling You This" — write something fresh and news-specific every day
   - No hashtags, no emojis in the title

2. "short_title": A YouTube Shorts title (max 60 characters). Punchy, curious, slightly alarming. No hashtags — those get added automatically.

3. "short_hook": A 45-second spoken script (≈100 words) for a YouTube Short.
   CRITICAL RULES — follow exactly:
   - Word 1 must be a shocking statement or number from today's story. No intro, no name, no "hey". Start mid-thought.
     Examples: "The Fed just lied to you." / "$39 trillion. That's the hole America is in." / "Wall Street just blinked."
   - Second sentence must make the viewer feel stupid for not knowing this already.
   - Middle: one punchy ELI5 analogy — explain the complex idea like the viewer is 12 years old.
   - End with: "Watch the full breakdown — link in bio." (spoken, not written)
   - Tone: urgent, slightly conspiratorial, like you're telling a secret.
   - No cues, no sponsor, no filler. Pure spoken words only. Every word earns its place.

4. "chapters": Array of chapter objects for the video description timestamps. Format:
   [{{"time": "0:00", "label": "Intro"}}, {{"time": "0:45", "label": "Topic Name"}}, ...]
   - 6-8 chapters covering the full video arc
   - Labels are short (3-5 words), punchy, SEO-friendly

5. "tags": Array of 8-10 topic-specific tags for today's story (single words or short phrases, no # prefix). Always include: "finance", "markets", "investing". Add tags specific to today's news.

6. "narration": The full ~10-minute spoken script following ALL these rules:
   - INTRO: Start with a massive high-stakes hook (0:00-1:00). After the hook, say "Welcome back to Tech Me Home, Market Phase daily news!"
   - TONE: Urgent, cinematic, educational. Slightly cynical about the Federal Reserve and fiat currency. Calm but dramatic.
   - SENTENCES: Short, punchy, conversational. Write how a person speaks.
   - CUES: Include [Visual:], [B-Roll:], [Sound effect:], [Graphic:] cues throughout
   - HUMOR: Deadpan sarcasm. "Magic/illusion" metaphors for fiat. Money printer "brrr" jokes.
   - ELI5: Explain one complex concept with a dead-simple analogy (coffee, Monopoly, casino)
   - SPONSOR: At ~2 min weave in a 30-sec [SPONSOR] pitch framed as "protect yourself"
   - OUTRO: Slightly optimistic. End with fast disclaimer: "None of this is financial advice, purely for entertainment, always do your own research..."
   - LENGTH: ~900 words (6 minutes at 150 words/minute) — be concise, cut any filler

3. "slides": Array of 8-10 slide objects. Each slide covers one section of the video. Format:
   {{
     "title": "SHORT SLIDE TITLE IN CAPS",
     "bullets": ["Bullet point 1", "Bullet point 2", "Bullet point 3"],
     "clip_tag": "tag_from_library_or_null",
     "pexels_keyword": "fallback search term if clip_tag is null",
     "narration_text": "The exact spoken words from the narration that play while this slide is shown"
   }}
   Rules for slides:
   - bullets: max 3 per slide, each max 10 words, key facts only — NO full sentences
   - clip_tag: pick the BEST matching tag from this library (or null if none fit well):
       stock_bull    → market rally, stocks rising, bullish sentiment
       stock_crash   → market drop, sell-off, fear, red day
       federal_reserve → Fed news, interest rate decisions, Powell
       wall_street   → trading floor, market open, brokers, equities
       inflation     → CPI, prices rising, cost of living, groceries
       gold          → safe haven, gold prices, commodities, precious metals
       crypto        → Bitcoin, Ethereum, digital assets, blockchain
       oil_energy    → oil prices, OPEC, energy sector, crude
       recession     → economic slowdown, GDP contraction, layoffs
       interest_rates → yield curve, bond yields, rate hike/cut
       global_economy → trade war, tariffs, international markets, GDP
       tech_stocks   → Nasdaq, semiconductors, AI stocks, big tech
       jobs          → unemployment, jobs report, payrolls, hiring
       bonds         → treasuries, bond market, fixed income, yields
       consumer      → retail sales, spending, credit cards, consumers
       earnings      → company earnings, profit, revenue, guidance
       nyse_open     → market open, NYSE, stock exchange, morning
       dollar        → USD, dollar index, currency, DXY
       bear_market   → prolonged decline, bear trend, capitulation
       data_screens  → data, analytics, charts, economic indicators
   - pexels_keyword: only needed when clip_tag is null — be specific and visual
   - narration_text: copy the exact portion of the narration script that belongs to this slide
   - First slide: hook/title card — use the most dramatic clip matching the story
   - Last slide: outro with MarketPhase branding — use nyse_open or data_screens
   - IMPORTANT: every word from the narration must appear in exactly one slide's narration_text — no gaps, no overlaps

Return ONLY valid JSON. No markdown, no explanation."""

    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 8000,
        "messages": [{"role": "user", "content": prompt}],
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

    raw = result["content"][0]["text"].strip()
    # Strip markdown code fences if present
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
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


# ── Claude: Shorts-only (lean prompt, no full narration) ─────────────────────

def call_claude_short(digest_summary: str, today_display: str, headlines=None) -> dict:
    """Generate only what's needed for a YouTube Short — no long narration or slides."""
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set")
    hl_block = ""
    if headlines:
        hl_block = ("\n\nTODAY'S RAW HEADLINES (prefer a SPECIFIC, dramatic one — a named "
                    "company/person/asset with a concrete number or event):\n"
                    + "\n".join(f"- {h}" for h in headlines[:25]))

    # Rotate a HIGH-AROUSAL angle daily. At this channel's scale you need the click
    # first — fear/greed/shock/curiosity drive Shorts reach. Vary WHICH high-arousal
    # lever (not down to "educational"), so it's not the same panic every day.
    ANGLES = [
        ("Money-at-risk warning",
         "Lead with what's about to hurt the viewer's money — savings, 401(k), home, job. "
         "Urgent and visceral. Open on the threat: 'Your retirement just took a hit and nobody "
         "told you.' Specific and personal, never vague."),
        ("Hidden opportunity",
         "The money-making angle the crowd is missing. What is smart money buying while everyone "
         "panics? 'While everyone's scared of X, the rich are quietly doing Y.'"),
        ("Contrarian shock",
         "Blow up the obvious take. Everyone believes X — here's why they're dead wrong. Bold, "
         "confrontational, counter-narrative."),
        ("Insider / smart-money move",
         "Expose what Wall Street and insiders are actually doing versus what retail is told. "
         "'Wall Street is quietly ___ — and it's not what they're telling you.'"),
        ("Wallet translation",
         "Translate the macro story straight into daily life — gas, groceries, rent, their "
         "paycheck, their 401(k). The money-in-their-pocket consequence IS the opening line."),
    ]
    angle_name, angle_dir = ANGLES[date.today().toordinal() % len(ANGLES)]

    prompt = f"""You are a YouTube Shorts scriptwriter for "Tech Me Home", a financial education channel by MarketPhase.
Today is {today_display}. Here is a summary of today's market news:

{digest_summary}{hl_block}

Pick ONE story and write a 55-60 second Short.

SUBJECT RULE (most important — this drives reach): the video MUST be about ONE specific
named entity — a company (Nvidia, Microsoft, SpaceX…), a person, or a specific asset
(oil, gold, a named stock) — tied to a concrete number or event. NEVER a generic subject
like "the market", "stocks", "investors", or "the economy". Name that entity in the title
AND the first spoken line. Specific-entity videos massively out-perform generic ones.

TODAY'S NARRATIVE ANGLE: {angle_name}
{angle_dir}
Deliver this angle with maximum stop-the-scroll energy. HIGH emotional stakes are the goal —
fear, greed, shock, and curiosity are what earn reach on Shorts. Vary which lever you pull day
to day so it's not identical panic, but never be boring, soft, or generic.

Output a JSON object with exactly these 5 keys:

1. "short_title": YouTube Shorts title, max 60 characters, no hashtags. High-stakes and
   impossible to scroll past — a specific number or a bold claim beats a vague summary.
   Good: "Your 401(k) Just Lost 8 Years Overnight". Bad: "A Look At Today's Market".

2. "short_hook": A 55-60 second spoken script (150-180 words minimum — count carefully).
   CRITICAL RULES — follow exactly:
   - FIRST 5 WORDS must hit hard: open on a shocking number or a personal-stakes threat that
     stops the swipe. No wind-up. e.g. "Your retirement just lost eight years." /
     "$1.2 trillion just vanished — here's who pays."
   - Then land what it means for the viewer's money, job, savings, or bills — never bury it.
   - Deliver the angle above in a fresh, specific voice with real tension.
   - Middle: two to three sentences of punchy ELI5 context. One surprising data point or
     comparison. Explain like the viewer is 12.
   - Tone: urgent, confident, a little insider — like a friend leaking a secret.
   - End with exactly: "Subscribe so tomorrow's biggest move hits your feed first."
   - No stage cues, no filler, no "hey", no intro, no name. Pure spoken words only.
   - MINIMUM 150 WORDS. Count before returning.

3. "clip_tags": An ORDERED array of 4 to 6 tags for a fast-cut background (a new clip every
   ~3-4 seconds), chosen to match the story's beats in sequence. Repeats allowed.
   ONLY choose from these 10 available clips — any other value is ignored:
   stock_bull, stock_crash, federal_reserve, wall_street, inflation,
   tech_stocks, earnings, nyse_open, data_screens, global_economy

4. "pexels_keyword": A 3-5 word image search term as fallback if no clip_tags match.

5. "tags": Array of 8-10 tags (no # prefix). Always include "finance", "markets",
   "investing", "Shorts". Add story-specific tags.

Return ONLY valid JSON. No markdown, no explanation."""

    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1200,
        "messages": [{"role": "user", "content": prompt}],
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

    raw = result["content"][0]["text"].strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
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


# ── ElevenLabs TTS ────────────────────────────────────────────────────────────

def strip_cues(script: str) -> str:
    clean = re.sub(r'\[.*?\]', '', script)
    clean = re.sub(r'\n{3,}', '\n\n', clean)
    return clean.strip()


def tts_elevenlabs(text: str, out_path: Path) -> Path:
    if not ELEVENLABS_API_KEY:
        raise ValueError("ELEVENLABS_API_KEY not set")

    voice_id = ELEVENLABS_VOICE_ID
    print(f"  Using voice ID: {voice_id} | model: {ELEVENLABS_MODEL}", file=sys.stderr)

    MAX_CHARS = 5000
    chunks = []
    while text:
        if len(text) <= MAX_CHARS:
            chunks.append(text)
            break
        split_at = text.rfind('. ', 0, MAX_CHARS)
        if split_at == -1:
            split_at = MAX_CHARS
        chunks.append(text[:split_at + 1])
        text = text[split_at + 1:].strip()

    def _synth(chunk_text: str, model: str) -> bytes:
        # stability 0.5 = "Natural" — a valid value for both v2 and v3 (v3
        # discretizes stability to 0.0/0.5/1.0). use_speaker_boost keeps the
        # cloned voice's identity under v3's wider dynamic range.
        payload = json.dumps({
            "text": chunk_text,
            "model_id": model,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "use_speaker_boost": True,
            },
        }).encode()
        req = urllib.request.Request(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            data=payload,
            headers={
                "xi-api-key": ELEVENLABS_API_KEY,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            method="POST",
        )
        with urlopen_with_retry(req, timeout=90) as resp:
            return resp.read()

    model = ELEVENLABS_MODEL
    audio_parts = []
    for i, chunk in enumerate(chunks):
        chunk_path = out_path.parent / f"audio_chunk_{i}.mp3"
        try:
            data = _synth(chunk, model)
        except Exception as e:
            if model != ELEVENLABS_FALLBACK_MODEL:
                print(f"  ⚠ {model} failed ({e}); falling back to "
                      f"{ELEVENLABS_FALLBACK_MODEL} for the rest of this run",
                      file=sys.stderr)
                model = ELEVENLABS_FALLBACK_MODEL   # stick with fallback for remaining chunks
                data = _synth(chunk, model)
            else:
                raise
        chunk_path.write_bytes(data)
        audio_parts.append(str(chunk_path))
        print(f"  Audio chunk {i+1}/{len(chunks)} done [{model}]", file=sys.stderr)
        time.sleep(1)

    if len(audio_parts) == 1:
        shutil.copy(audio_parts[0], out_path)
    else:
        list_file = out_path.parent / "concat_list.txt"
        list_file.write_text("\n".join(f"file '{p}'" for p in audio_parts))
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(list_file), "-c", "copy", str(out_path)
        ], check=True, capture_output=True)

    return out_path


# ── Pexels image fetch ────────────────────────────────────────────────────────

def fetch_pexels_image(keyword: str, idx: int, tmp_dir: Path) -> Path | None:
    """Try Pexels first, fall back to Pixabay."""
    img_path = tmp_dir / f"bg_{idx:03d}.jpg"

    def _download_image(url: str, dest: Path) -> bool:
        """Download an image URL to dest, following redirects with proper headers."""
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; MarketPhase/1.0)",
                    "Accept": "image/jpeg,image/png,image/*",
                },
            )
            with urlopen_with_retry(req, timeout=45, backoff=5) as resp:
                data = resp.read()
            if len(data) < 1000:
                print(f"  Download too small ({len(data)} bytes), skipping", file=sys.stderr)
                return False
            dest.write_bytes(data)
            return True
        except Exception as e:
            print(f"  Image download failed ({url[:60]}): {e}", file=sys.stderr)
            return False

    # ── Try Pexels ──
    if PEXELS_API_KEY:
        try:
            query = urllib.parse.quote(keyword)
            req = urllib.request.Request(
                f"https://api.pexels.com/v1/search?query={query}&per_page=8&orientation=landscape",
                headers={
                    "Authorization": PEXELS_API_KEY.strip(),
                    "User-Agent": "MarketPhase/1.0 (https://market-phase.com)",
                },
            )
            with urlopen_with_retry(req, timeout=30, backoff=5) as resp:
                data = json.loads(resp.read())
            photos = data.get("photos", [])
            if photos:
                photo = random.choice(photos)
                img_url = photo["src"].get("large2x") or photo["src"].get("large") or photo["src"]["original"]
                print(f"  [Pexels] '{keyword}' → {img_url[:60]}", file=sys.stderr)
                if _download_image(img_url, img_path):
                    return img_path
            else:
                print(f"  [Pexels] no photos for '{keyword}'", file=sys.stderr)
        except Exception as e:
            print(f"  Pexels failed ('{keyword}'): {e}", file=sys.stderr)

    # ── Fall back to Pixabay ──
    if PIXABAY_API_KEY:
        try:
            query = urllib.parse.quote(keyword)
            req = urllib.request.Request(
                f"https://pixabay.com/api/?key={PIXABAY_API_KEY.strip()}"
                f"&q={query}&image_type=photo&orientation=horizontal"
                f"&per_page=8&safesearch=true",
                headers={"User-Agent": "Mozilla/5.0 (compatible; MarketPhase/1.0)"},
            )
            with urlopen_with_retry(req, timeout=30, backoff=5) as resp:
                raw = resp.read()
            data = json.loads(raw)
            hits = data.get("hits", [])
            print(f"  [Pixabay] '{keyword}' → {len(hits)} hits", file=sys.stderr)
            if hits:
                hit = random.choice(hits)
                # webformatURL is always accessible; largeImageURL needs partner access
                img_url = hit.get("webformatURL") or hit.get("largeImageURL")
                print(f"  [Pixabay] downloading {img_url[:60]}", file=sys.stderr)
                if img_url and _download_image(img_url, img_path):
                    return img_path
        except Exception as e:
            print(f"  Pixabay failed ('{keyword}'): {e}", file=sys.stderr)

    print(f"  No image found for '{keyword}', using solid background", file=sys.stderr)
    return None


def get_clip_for_slide(tag: str):
    """Return path to a pre-generated Seedance clip, or None if not available."""
    if not tag:
        return None
    clip = CLIPS_DIR / f"{tag}.mp4"
    if clip.exists():
        print(f"  [Clip] using library clip: {tag}.mp4", file=sys.stderr)
        return clip
    print(f"  [Clip] '{tag}' not in library, falling back to image", file=sys.stderr)
    return None


# ── Slide rendering ───────────────────────────────────────────────────────────

def get_font(size, bold=False):
    from PIL import ImageFont
    paths_bold = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
        # macOS fallbacks (local dev/testing — Linux paths above win on CI)
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/System/Library/Fonts/HelveticaNeue.ttc",
    ]
    paths_reg = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for fp in (paths_bold if bold else paths_reg):
        if Path(fp).exists():
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


def render_overlay_png(slide: dict, idx: int, total: int, tmp_dir: Path) -> Path:
    """Render text/branding as a transparent RGBA PNG — no background.
    This gets composited on top of the clip/image by ffmpeg."""
    from PIL import Image, ImageDraw

    ACCENT = (29, 78, 216)
    WHITE  = (255, 255, 255)
    YELLOW = (251, 191, 36)
    MUTED  = (148, 163, 184)
    RED    = (239, 68, 68)

    title    = slide.get("title", "MARKET UPDATE")
    bullets  = slide.get("bullets", [])
    is_first = idx == 0
    is_last  = idx == total - 1
    today_str = date.today().strftime("%B %d, %Y")

    # Start fully transparent
    img  = Image.new("RGBA", (SLIDE_W, SLIDE_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # ── Dark gradient overlay so text pops over any background ──
    gradient_top = int(SLIDE_H * 0.15)
    for y in range(gradient_top, SLIDE_H):
        alpha = int(210 * (y - gradient_top) / (SLIDE_H - gradient_top))
        draw.rectangle([(0, y), (SLIDE_W, y + 1)], fill=(5, 10, 20, alpha))

    # ── Top accent bar ──
    draw.rectangle([(0, 0), (SLIDE_W, 6)], fill=ACCENT + (255,))

    # ── MarketPhase logo top-left ──
    brand_font = get_font(30, bold=True)
    draw.text((50, 28), "MARKET", font=brand_font, fill=WHITE + (255,))
    mw = draw.textlength("MARKET", font=brand_font)
    draw.text((50 + mw, 28), "PHASE", font=brand_font, fill=(96, 165, 250, 255))

    # ── Channel name top-right ──
    ch_font = get_font(22)
    draw.text((SLIDE_W - 350, 32), "Tech Me Home", font=ch_font, fill=MUTED + (200,))

    # ── Date bottom-right ──
    draw.text((SLIDE_W - 280, SLIDE_H - 50), today_str,
              font=get_font(22), fill=MUTED + (200,))

    # ── Slide counter bottom-left ──
    draw.text((50, SLIDE_H - 50), f"{idx + 1} / {total}",
              font=get_font(20), fill=MUTED + (180,))

    # ── Bottom accent bar ──
    draw.rectangle([(0, SLIDE_H - 5), (SLIDE_W, SLIDE_H)], fill=RED + (255,))

    # ── Title ──
    title_font  = get_font(90 if is_first else 72, bold=True)
    title_color = YELLOW + (255,) if is_first else WHITE + (255,)
    title_wrapped = textwrap.fill(title, width=30)
    title_lines   = title_wrapped.split('\n')
    title_h = len(title_lines) * 82
    title_y = SLIDE_H // 2 - title_h // 2 - (80 if bullets else 0)
    for li, line in enumerate(title_lines):
        # Soft shadow
        draw.text((82, title_y + li * 82 + 2), line, font=title_font, fill=(0, 0, 0, 140))
        draw.text((80, title_y + li * 82),     line, font=title_font, fill=title_color)

    # ── Bullet points ──
    if bullets:
        bullet_font = get_font(46)
        bullet_y    = title_y + title_h + 40
        for bi, bullet in enumerate(bullets[:3]):
            dot_x = 80
            dot_y = bullet_y + bi * 65 + 20
            draw.ellipse([(dot_x, dot_y), (dot_x + 14, dot_y + 14)],
                         fill=YELLOW + (255,))
            draw.text((dot_x + 30, bullet_y + bi * 65), bullet,
                      font=bullet_font, fill=WHITE + (255,))

    # ── Last slide: site URL ──
    if is_last:
        draw.text((80, SLIDE_H - 130), f"Learn more: {SITE_URL}",
                  font=get_font(36, bold=True), fill=(96, 165, 250, 255))

    out = tmp_dir / f"overlay_{idx:03d}.png"
    img.save(out, "PNG")
    return out


def composite_slide_video(bg_source: Path, overlay_png: Path,
                          duration: float, out_path: Path, is_video_bg: bool):
    """
    Composite overlay PNG on top of bg_source (clip or image) for `duration` seconds.
    - is_video_bg=True  → slow clip to 0.25x speed (setpts=4*PTS), loop if needed
    - is_video_bg=False → freeze the static image
    """
    if is_video_bg:
        # Slow clip to 0.25x playback speed: 5-sec clip → 20 sec effective
        # Calculate loops needed so slowed content covers full slide duration
        SLOW = 4.0          # 0.25x speed = 4× PTS multiplier
        CLIP_SEC = 5.0      # source clip duration
        loops = max(0, int(duration / (CLIP_SEC * SLOW)) + 1)
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", str(loops), "-i", str(bg_source),
            "-i", str(overlay_png),
            "-filter_complex",
            f"[0:v]setpts={SLOW}*PTS,scale={SLIDE_W}:{SLIDE_H},setsar=1[bg];"
            f"[bg][1:v]overlay=0:0[out]",
            "-map", "[out]",
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-an",
            str(out_path),
        ]
    else:
        # Static image looped then overlay
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-t", str(duration), "-i", str(bg_source),
            "-i", str(overlay_png),
            "-filter_complex",
            f"[0:v]scale={SLIDE_W}:{SLIDE_H},setsar=1[bg];"
            f"[bg][1:v]overlay=0:0[out]",
            "-map", "[out]",
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-an",
            str(out_path),
        ]
    subprocess.run(cmd, check=True, capture_output=True)


def create_slides(slides_data: list[dict], durations: list[float],
                  tmp_dir: Path) -> list[Path]:
    """
    For each slide:
      1. Pick background: Seedance clip → Pexels/Pixabay image → solid colour
      2. Render transparent text overlay PNG
      3. ffmpeg composite → slide_NNN.mp4
    Returns list of .mp4 slide segment paths.
    """
    from PIL import Image

    BG_DARK = (10, 15, 30)
    total   = len(slides_data)
    segment_paths = []

    for idx, (slide, dur) in enumerate(zip(slides_data, durations)):
        title   = slide.get("title", "MARKET UPDATE")
        tag     = slide.get("clip_tag")
        keyword = slide.get("pexels_keyword", "finance stock market")

        print(f"  Slide {idx+1}/{total}: {title}", file=sys.stderr)

        # ── 1. Choose background ──
        clip_path = get_clip_for_slide(tag)
        is_video_bg = clip_path is not None

        if not is_video_bg:
            # Try Pexels/Pixabay still image
            img_path = fetch_pexels_image(keyword, idx, tmp_dir)
            if img_path and img_path.exists():
                bg_source = img_path
            else:
                # Solid dark fallback
                fb = tmp_dir / f"bg_solid_{idx:03d}.png"
                Image.new("RGB", (SLIDE_W, SLIDE_H), BG_DARK).save(fb, "PNG")
                bg_source = fb
        else:
            bg_source = clip_path

        # ── 2. Render text overlay PNG ──
        overlay_png = render_overlay_png(slide, idx, total, tmp_dir)

        # ── 3. Composite → slide video segment ──
        seg_out = tmp_dir / f"slide_{idx:03d}.mp4"
        composite_slide_video(bg_source, overlay_png, dur, seg_out, is_video_bg)
        segment_paths.append(seg_out)

    return segment_paths


# ── Video assembly ────────────────────────────────────────────────────────────

def get_audio_duration(audio_path: Path) -> float:
    result = subprocess.run([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", str(audio_path)
    ], capture_output=True, text=True)
    info = json.loads(result.stdout)
    return float(info["format"]["duration"])


def calc_slide_durations(slides_data: list[dict], audio_duration: float) -> list[float]:
    """Allocate slide duration proportionally by word count in each slide's narration_text."""
    word_counts = []
    for slide in slides_data:
        text = slide.get("narration_text", slide.get("title", "placeholder"))
        word_counts.append(max(1, len(text.split())))
    total_words = sum(word_counts)
    durations = [(wc / total_words) * audio_duration for wc in word_counts]
    # Ensure minimum 3 seconds per slide
    durations = [max(3.0, d) for d in durations]
    # Re-scale to match total audio duration
    scale = audio_duration / sum(durations)
    return [d * scale for d in durations]


def build_video(segment_paths: list[Path], audio_path: Path, out_path: Path):
    """Concat pre-composited slide .mp4 segments and mux with audio."""
    audio_duration = get_audio_duration(audio_path)
    num_slides = len(segment_paths)
    avg = audio_duration / num_slides

    print(f"  Building video ({audio_duration:.0f}s, {num_slides} slides, "
          f"~{avg:.1f}s avg/slide)…", file=sys.stderr)

    # Write concat list (segments already have correct durations)
    concat_file = out_path.parent / "slides_concat.txt"
    with concat_file.open("w") as f:
        for seg in segment_paths:
            f.write(f"file '{seg.resolve()}'\n")

    subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-i", str(audio_path),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        str(out_path),
    ], check=True, capture_output=True)
    print(f"  Video saved: {out_path}", file=sys.stderr)


# ── YouTube upload ────────────────────────────────────────────────────────────

def get_youtube_access_token() -> str:
    payload = urllib.parse.urlencode({
        "client_id": YOUTUBE_CLIENT_ID,
        "client_secret": YOUTUBE_CLIENT_SECRET,
        "refresh_token": YOUTUBE_REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen_with_retry(req, timeout=60) as resp:
        result = json.loads(resp.read())
    return result["access_token"]


def remove_green_screen(img):
    """Chroma-key remove the solid green background."""
    import numpy as np
    from PIL import Image
    arr = np.array(img.convert("RGBA")).astype(float)
    r, g, b = arr[:,:,0], arr[:,:,1], arr[:,:,2]
    # Green screen: G channel dominant, well above R and B
    mask = (g > 80) & (g > r * 1.35) & (g > b * 1.35)
    # Soft edge — slightly fade near-green pixels
    edge = (g > 60) & (g > r * 1.2) & (g > b * 1.2) & ~mask
    arr[mask, 3] = 0
    arr[edge, 3] = arr[edge, 3] * 0.4
    return Image.fromarray(arr.astype('uint8'), 'RGBA')


HOST_POSES = ["host_1.jpeg", "host_2.jpeg"]  # ONE real person, multiple poses (Asian host)


def prepare_host_pngs(tmp_dir: Path, target_h: int = 700):
    """Cutouts of the ONE consistent real host across their poses — green-screen
    removed + despilled, cropped to head+torso, sized for a bottom-corner presenter.
    Returns a list of paths to SEQUENCE through (jump-cut between poses = alive, same
    identity), or [] → faceless fallback. (Rotating *different* faces or a static
    full-screen photo was the old mistake.)"""
    from PIL import Image
    import numpy as np
    assets, out = Path(__file__).parent / "assets", []
    for i, name in enumerate(HOST_POSES):
        src = assets / name
        if not src.exists():
            continue
        try:
            img = remove_green_screen(Image.open(src))
            # Despill: clamp green-dominant pixels' green to max(R,B) → kills the keyed
            # green halo without touching skin/shirt tones.
            arr = np.array(img).astype(np.int16)
            mx  = np.maximum(arr[:, :, 0], arr[:, :, 2])
            arr[:, :, 1] = np.where(arr[:, :, 1] > mx, mx, arr[:, :, 1])
            img = Image.fromarray(np.clip(arr, 0, 255).astype("uint8"), "RGBA")
            a   = np.array(img)[:, :, 3]
            ys, xs = np.where(a > 30)
            if len(ys) == 0:
                continue
            person = img.crop((int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())))
            person = person.crop((0, 0, person.width, int(person.height * 0.62)))  # head+torso
            scale  = target_h / person.height
            person = person.resize((max(1, int(person.width * scale)), target_h), Image.LANCZOS)
            p = tmp_dir / f"host_{i}.png"; person.save(p, "PNG"); out.append(p)
        except Exception as e:
            print(f"  [host] {name} failed ({e})", file=sys.stderr)
    return out


def draw_outlined_text(draw, pos, text, font, fill, outline=(0,0,0), thickness=4):
    """Draw text with a thick outline for maximum contrast on any background."""
    x, y = pos
    for dx in range(-thickness, thickness + 1):
        for dy in range(-thickness, thickness + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=outline)
    draw.text((x, y), text, font=font, fill=fill)


def generate_thumbnail(title: str, pexels_keyword: str, tmp_dir: Path) -> Path:
    """
    High-impact YouTube thumbnail:
    - Seedance clip frame (or Pexels) as background — vibrant, not too dark
    - Strong vignette + right-side gradient for text area
    - Host photo left — large, full-height
    - Title right — BIG font, thick outline, yellow highlight bar on line 1
    - MarketPhase branding + red bottom bar
    """
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter, ImageEnhance

    TW, TH   = 1280, 720
    YELLOW   = (251, 191, 36)
    WHITE    = (255, 255, 255)
    RED      = (220, 38, 38)
    ACCENT   = (29, 78, 216)
    DARK     = (5, 10, 20)

    # ── Background: prefer Seedance clip frame, fallback to Pexels ──
    clip_path = get_clip_for_slide(pexels_keyword.replace(" ", "_"))
    bg = None
    if clip_path:
        frame_path = tmp_dir / "thumb_bg_frame.png"
        try:
            subprocess.run([
                "ffmpeg", "-y", "-i", str(clip_path),
                "-vf", f"scale={TW}:{TH}:force_original_aspect_ratio=increase,"
                       f"crop={TW}:{TH}",
                "-frames:v", "1", "-q:v", "2", str(frame_path)
            ], check=True, capture_output=True)
            bg = Image.open(frame_path).convert("RGB")
            # Keep it relatively bright — not too dark
            bg = ImageEnhance.Brightness(bg).enhance(0.7)
        except Exception:
            bg = None

    if bg is None:
        img_path = fetch_pexels_image(pexels_keyword, 98, tmp_dir)
        if img_path and img_path.exists():
            bg = Image.open(img_path).convert("RGB").resize((TW, TH), Image.LANCZOS)
            bg = ImageEnhance.Brightness(bg).enhance(0.7)
        else:
            bg = Image.new("RGB", (TW, TH), (15, 20, 40))

    bg = bg.convert("RGBA")

    # ── Vignette (darkens edges, keeps centre bright) ──
    vig = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
    vd  = ImageDraw.Draw(vig)
    for i in range(80):
        alpha = int(160 * (i / 80) ** 1.5)
        vd.rectangle([(i, i), (TW - i, TH - i)], outline=(0, 0, 0, alpha))
    bg = Image.alpha_composite(bg, vig)

    # ── Dark gradient over right 55% for text legibility ──
    grad = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
    gd   = ImageDraw.Draw(grad)
    split = int(TW * 0.38)
    for x in range(split, TW):
        alpha = int(200 * ((x - split) / (TW - split)) ** 0.6)
        gd.rectangle([(x, 0), (x + 1, TH)], fill=DARK + (alpha,))
    bg = Image.alpha_composite(bg, grad)

    # ── Host photo — large, left side ──
    assets_dir = Path(__file__).parent / "assets"
    # One consistent real host everywhere (host_1) — not a rotating cast of faces.
    host_1     = assets_dir / "host_1.jpeg"
    host_files = [host_1] if host_1.exists() else sorted(assets_dir.glob("host_*.jp*g"))
    if host_files:
        host_path = host_files[0]
        print(f"  Thumbnail host: {host_path.name}", file=sys.stderr)
        host_img  = Image.open(host_path)
        host_img  = remove_green_screen(host_img)
        target_h  = int(TH * 1.08)
        scale     = target_h / host_img.height
        target_w  = int(host_img.width * scale)
        host_img  = host_img.resize((target_w, target_h), Image.LANCZOS)
        x_pos     = int(TW * 0.02)
        y_pos     = TH - target_h + 10
        bg.paste(host_img, (x_pos, y_pos), host_img)

    draw   = ImageDraw.Draw(bg)
    x_text = int(TW * 0.42)
    x_max  = TW - 30
    max_w  = x_max - x_text

    # ── Word-wrap title at large font size ──
    font_size = 88
    title_font = get_font(font_size, bold=True)
    words = title.upper().split()
    lines, current = [], []
    for word in words:
        test = ' '.join(current + [word])
        if draw.textlength(test, font=title_font) < max_w:
            current.append(word)
        else:
            if current:
                lines.append(' '.join(current))
            current = [word]
    if current:
        lines.append(' '.join(current))

    line_h  = font_size + 14
    total_h = len(lines) * line_h
    y_start = (TH - total_h) // 2 - 10

    for i, line in enumerate(lines):
        y = y_start + i * line_h
        if i == 0:
            # Yellow highlight bar behind first line
            lw = draw.textlength(line, font=title_font)
            draw.rectangle(
                [(x_text - 8, y - 4), (x_text + lw + 8, y + font_size + 4)],
                fill=(251, 191, 36, 230)
            )
            draw_outlined_text(draw, (x_text, y), line, title_font,
                               fill=(10, 10, 10), outline=(0, 0, 0), thickness=2)
        else:
            draw_outlined_text(draw, (x_text, y), line, title_font,
                               fill=WHITE, outline=(0, 0, 0), thickness=5)

    # ── LIVE badge top-right ──
    badge_font = get_font(22, bold=True)
    draw.rectangle([(TW - 130, 14), (TW - 14, 46)], fill=RED)
    draw.text((TW - 118, 18), "DAILY NEWS", font=badge_font, fill=WHITE)

    # ── MarketPhase branding bottom-left ──
    brand_font = get_font(28, bold=True)
    draw.rectangle([(0, TH - 52), (220, TH)], fill=(0, 0, 0, 180))
    draw_outlined_text(draw, (14, TH - 44), "MARKET", brand_font,
                       fill=WHITE, outline=(0,0,0), thickness=1)
    mw = draw.textlength("MARKET", font=brand_font)
    draw_outlined_text(draw, (14 + mw, TH - 44), "PHASE", brand_font,
                       fill=(96, 165, 250), outline=(0,0,0), thickness=1)

    # ── Red bottom bar ──
    draw.rectangle([(0, TH - 6), (TW, TH)], fill=RED)

    out = tmp_dir / "thumbnail.jpg"
    bg.convert("RGB").save(out, "JPEG", quality=95)
    print(f"  Thumbnail saved: {out}", file=sys.stderr)
    return out


def set_youtube_thumbnail(video_id: str, thumbnail_path: Path, access_token: str):
    """Upload a custom thumbnail image for the video."""
    try:
        img_bytes = thumbnail_path.read_bytes()
        req = urllib.request.Request(
            f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
            f"?videoId={video_id}&uploadType=media",
            data=img_bytes,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "image/jpeg",
                "Content-Length": str(len(img_bytes)),
            },
            method="POST",
        )
        with urlopen_with_retry(req, timeout=90) as resp:
            resp.read()
        print(f"  Thumbnail set ✅", file=sys.stderr)
    except Exception as e:
        print(f"  Thumbnail upload failed (non-fatal): {e}", file=sys.stderr)


def upload_to_youtube(video_path: Path, title: str, hook_text: str,
                      thumbnail_path=None, chapters=None, extra_tags=None) -> str:
    access_token = get_youtube_access_token()
    today_str = date.today().strftime("%B %d, %Y")

    # ── Chapters block ──
    chapters_block = ""
    if chapters:
        chapters_block = "⏱️ CHAPTERS\n"
        chapters_block += "\n".join(f"{c['time']} {c['label']}" for c in chapters)
        chapters_block += "\n\n"

    description = (
        f"{hook_text}\n\n"
        f"👉 Full market analysis & signals: {SITE_URL}\n\n"
        f"{chapters_block}"
        f"Track live market signals, economic indicators, and daily market analysis "
        f"at MarketPhase — free institutional-grade tools for everyday investors.\n\n"
        f"📅 {today_str}  |  New video every weekday at 6:30 AM ET\n\n"
        f"#markets #finance #investing #stocks #economy #MarketPhase #TechMeHome "
        f"#stockmarket #financialnews #marketupdate\n\n"
        f"⚠️ None of this is financial advice. For entertainment and educational "
        f"purposes only. Always do your own research."
    )

    base_tags = ["markets", "finance", "investing", "stocks", "economy",
                 "MarketPhase", "TechMeHome", "market update", "daily news",
                 "financial news", "stock market today"]
    all_tags = list(dict.fromkeys(base_tags + (extra_tags or [])))

    metadata = json.dumps({
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": all_tags[:30],
            "categoryId": "25",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        }
    }).encode()

    boundary = "==marketphase_boundary=="
    video_bytes = video_path.read_bytes()

    body = (
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
    ).encode() + metadata + (
        f"\r\n--{boundary}\r\nContent-Type: video/mp4\r\n\r\n"
    ).encode() + video_bytes + f"\r\n--{boundary}--".encode()

    req = urllib.request.Request(
        "https://www.googleapis.com/upload/youtube/v3/videos"
        "?uploadType=multipart&part=snippet,status",
        data=body,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": f"multipart/related; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        result = json.loads(resp.read())

    video_id = result["id"]
    url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"  Uploaded: {url}", file=sys.stderr)

    # Set custom thumbnail
    if thumbnail_path and thumbnail_path.exists():
        set_youtube_thumbnail(video_id, thumbnail_path, access_token)

    return url


# ── YouTube Shorts pipeline ───────────────────────────────────────────────────

SHORT_W, SHORT_H = 1080, 1920  # vertical 9:16

def transcribe_words(audio_path: Path):
    """Word-level timestamps via faster-whisper. Returns [(text, start, end)] or []
    on any failure (captions are best-effort — never break the render)."""
    try:
        from faster_whisper import WhisperModel
    except Exception as e:
        print(f"  [captions] faster-whisper unavailable ({e}); skipping captions", file=sys.stderr)
        return []
    try:
        size  = os.environ.get("WHISPER_MODEL", "base")
        model = WhisperModel(size, device="cpu", compute_type="int8")
        segs, _ = model.transcribe(str(audio_path), word_timestamps=True)
        words = []
        for s in segs:
            for w in (s.words or []):
                t = w.word.strip()
                if t:
                    words.append((t, float(w.start), float(w.end)))
        print(f"  [captions] {len(words)} words aligned", file=sys.stderr)
        return words
    except Exception as e:
        print(f"  [captions] transcription failed ({e}); skipping captions", file=sys.stderr)
        return []


def build_caption_pngs(words, tmp_dir: Path):
    """Hype color-pop captions: a 1-3 word window with the ACTIVE word popped in
    brand-yellow, rest white, thick outline. Returns [(png, start, end)] for
    ffmpeg overlay timing. Uses PIL (no libass) so fonts are guaranteed present."""
    from PIL import Image, ImageDraw
    if not words:
        return []
    YELLOW = (251, 191, 36, 255)
    WHITE  = (255, 255, 255, 255)
    font   = get_font(92, bold=True)
    space  = 26
    y       = int(SHORT_H * 0.60)   # lower-third, clear of top title + bottom CTA

    # Group into chunks of ≤3 words; also break on a pause > 0.6s.
    chunks, cur = [], []
    for w in words:
        if cur and (len(cur) >= 3 or w[1] - cur[-1][2] > 0.6):
            chunks.append(cur); cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)

    scratch = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    raw, k = [], 0
    for chunk in chunks:
        txts   = [t.upper() for (t, _, _) in chunk]
        widths = [scratch.textlength(t, font=font) for t in txts]
        total  = sum(widths) + space * (len(txts) - 1)
        x0     = int((SHORT_W - total) // 2)
        for ai, (_, ws, we) in enumerate(chunk):
            img = Image.new("RGBA", (SHORT_W, SHORT_H), (0, 0, 0, 0))
            d   = ImageDraw.Draw(img)
            x   = x0
            for wi, t in enumerate(txts):
                draw_outlined_text(d, (x, y), t, font,
                                   YELLOW if wi == ai else WHITE,
                                   outline=(0, 0, 0, 255), thickness=7)
                x += widths[wi] + space
            png = tmp_dir / f"cap_{k:03d}.png"
            img.save(png, "PNG"); k += 1
            raw.append((png, ws, we))
    # Contiguous, NON-overlapping windows: each caption ends exactly when the next
    # begins (minus a tiny margin) → never two captions on screen at once.
    items = []
    for i, (png, ws, we) in enumerate(raw):
        end = (raw[i + 1][1] - 0.02) if i + 1 < len(raw) else we + 0.15
        items.append((png, round(ws, 2), round(max(end, ws + 0.05), 2)))
    print(f"  [captions] {len(items)} caption frames built", file=sys.stderr)
    return items


def burn_captions(base_video: Path, items, duration: float, out_path: Path) -> Path:
    """Overlay timed caption PNGs onto base_video via ffmpeg enable windows."""
    inputs = []
    for png, _, _ in items:
        inputs += ["-i", str(png)]
    fc, cur = [], "0:v"
    for idx, (_, s, e) in enumerate(items, start=1):
        nxt = f"c{idx}"
        fc.append(f"[{cur}][{idx}:v]overlay=0:0:enable='between(t,{s},{e})'[{nxt}]")
        cur = nxt
    subprocess.run([
        "ffmpeg", "-y", "-i", str(base_video), *inputs,
        "-filter_complex", ";".join(fc),
        "-map", f"[{cur}]", "-t", f"{duration:.2f}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-an", str(out_path),
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_path


def render_hook_frames(title: str, dur: float, tmp_dir: Path):
    """Animated opening HOOK card: big centered title that pops in over the montage.
    Owns the first ~2-3s (the swipe-decision window) instead of a static title card.
    Returns [(png, start, end)] covering [0, dur]."""
    from PIL import Image, ImageDraw
    YELLOW = (251, 191, 36, 255)
    base   = 108

    def render(scale, k):
        img = Image.new("RGBA", (SHORT_W, SHORT_H), (0, 0, 0, 0))
        d   = ImageDraw.Draw(img)
        # dark scrim behind the hook so it reads over moving footage
        d.rectangle([(0, int(SHORT_H * 0.27)), (SHORT_W, int(SHORT_H * 0.73))],
                    fill=(0, 0, 0, 96))
        size   = max(20, int(base * scale))
        f      = get_font(size, bold=True)
        lines  = _wrap_text(d, title.upper(), f, SHORT_W - 110)
        line_h = int(size * 1.15)
        y      = (SHORT_H - line_h * len(lines)) // 2
        for ln in lines:
            lw = d.textlength(ln, font=f)
            draw_outlined_text(d, (int((SHORT_W - lw) // 2), y), ln, f,
                               YELLOW, outline=(0, 0, 0, 255), thickness=8)
            y += line_h
        png = tmp_dir / f"hook_{k:02d}.png"; img.save(png, "PNG")
        return png

    # Pop-in entrance (0.80→1.03 overshoot→1.0), then hold until dur.
    steps  = [(0.00, 0.80), (0.06, 0.90), (0.12, 0.97), (0.18, 1.03), (0.24, 1.0)]
    frames = []
    for i, (t0, sc) in enumerate(steps):
        png = render(sc, i)
        t1  = steps[i + 1][0] if i + 1 < len(steps) else 0.30
        frames.append((png, round(t0, 2), round(t1, 2)))
    frames.append((render(1.0, len(steps)), 0.30, round(max(dur, 0.5), 2)))
    return frames


def build_montage_bg(clip_paths, duration: float, tmp_dir: Path) -> Path:
    """Fast-cut montage: a new clip every ~3.5s at normal speed. Returns bg video."""
    SEG = 3.5
    n_segs = int(duration // SEG) + 1
    seg_paths = []
    for i in range(n_segs):
        clip = clip_paths[i % len(clip_paths)]
        seg  = tmp_dir / f"mseg_{i:02d}.mp4"
        subprocess.run([
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", str(clip),
            "-t", f"{SEG:.2f}",
            "-vf", (f"scale={SHORT_W}:{SHORT_H}:force_original_aspect_ratio=increase,"
                    f"crop={SHORT_W}:{SHORT_H},setsar=1,fps=30,format=yuv420p"),
            "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-video_track_timescale", "30000",
            str(seg),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        seg_paths.append(seg)
    list_file = tmp_dir / "montage.txt"
    list_file.write_text("\n".join(f"file '{p}'" for p in seg_paths))
    bg_video = tmp_dir / "montage_bg.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-t", f"{duration:.2f}", "-c", "copy", str(bg_video),
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return bg_video


def generate_short_video(short_hook: str, short_title: str,
                         clip_tags, tmp_dir: Path) -> Path:
    """Render a vertical YouTube Short: fast-cut clip montage + bold hook text.

    clip_tags may be a LIST of tags (preferred — a new clip every ~3-4s) or a
    single tag string (back-compat). The static host photo is intentionally gone
    (faceless/dynamic format) — visual change every few seconds drives retention.
    """
    from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
    import numpy as np

    YELLOW = (251, 191, 36)
    WHITE  = (255, 255, 255)
    RED    = (239, 68, 68)
    ACCENT = (29, 78, 216)

    # ── Normalize clip tags → ordered list of existing clip paths ──
    if isinstance(clip_tags, str):
        clip_tags = [clip_tags]
    clip_paths = []
    for t in (clip_tags or []):
        if not t:
            continue
        p = get_clip_for_slide(t)
        if p and (not clip_paths or clip_paths[-1] != p):  # skip consecutive dupes
            clip_paths.append(p)

    if clip_paths:
        # Transparent canvas — the moving clip montage becomes the bg layer.
        # The overlay only carries text/branding so the clips play through.
        bg = Image.new("RGBA", (SHORT_W, SHORT_H), (0, 0, 0, 0))
    else:
        bg = Image.new("RGBA", (SHORT_W, SHORT_H), (10, 15, 30, 255))

    # ── Dark gradient (semi-transparent so clip shows through at the top) ──
    grad = Image.new("RGBA", (SHORT_W, SHORT_H), (0, 0, 0, 0))
    gd   = ImageDraw.Draw(grad)
    for y in range(SHORT_H // 3, SHORT_H):
        alpha = int(200 * (y - SHORT_H // 3) / (SHORT_H * 2 / 3))
        gd.rectangle([(0, y), (SHORT_W, y + 1)], fill=(5, 10, 20, alpha))
    bg = Image.alpha_composite(bg, grad)

    draw = ImageDraw.Draw(bg)

    # ── Top accent bar ──
    draw.rectangle([(0, 0), (SHORT_W, 8)], fill=ACCENT + (255,))

    # ── MARKETPHASE branding ──
    brand_font = get_font(38, bold=True)
    draw.text((40, 40), "MARKET", font=brand_font, fill=WHITE + (255,))
    mw = draw.textlength("MARKET", font=brand_font)
    draw.text((40 + mw, 40), "PHASE", font=brand_font, fill=(96, 165, 250, 255))

    # (No persistent title — the opening HOOK card, rendered separately, owns the
    #  first ~2.5s; kinetic captions carry the text after that.)

    # ── Follow CTA (host photo removed → faceless/dynamic format) ──
    # Shorts "Related video" links are Studio-only (not in the Data API), so we
    # drive follows rather than point to a "link in bio" that YouTube hides.
    cta_font = get_font(48, bold=True)
    cta = "SUBSCRIBE for tomorrow's move"
    cw  = draw.textlength(cta, font=cta_font)
    pad = 26
    draw.rounded_rectangle(
        [((SHORT_W - cw) // 2 - pad, SHORT_H - 134),
         ((SHORT_W + cw) // 2 + pad, SHORT_H - 134 + 72)],
        radius=16, fill=(220, 38, 38, 220))   # red pill = the Subscribe colour
    draw.text(((SHORT_W - cw) // 2, SHORT_H - 120), cta,
              font=cta_font, fill=(255, 255, 255, 255))

    # ── Bottom bar ──
    draw.rectangle([(0, SHORT_H - 8), (SHORT_W, SHORT_H)], fill=RED + (255,))

    # ── Build video: static overlay over a fast-cut clip montage ──
    overlay_path = tmp_dir / "short_overlay.png"
    bg.convert("RGBA").save(overlay_path, "PNG")

    # TTS for the short
    short_audio = tmp_dir / "short_narration.mp3"
    tts_elevenlabs(short_hook, short_audio)
    short_duration = get_audio_duration(short_audio)

    # Pad audio to at least 45 seconds so YouTube treats it as a proper Short
    MIN_DURATION = 45.0
    if short_duration < MIN_DURATION:
        pad = MIN_DURATION - short_duration
        padded_audio = tmp_dir / "short_narration_padded.mp3"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(short_audio),
            "-af", f"apad=pad_dur={pad:.1f}",
            "-c:a", "libmp3lame", "-b:a", "192k",
            str(padded_audio),
        ], check=True, stdout=subprocess.DEVNULL)
        short_audio    = padded_audio
        short_duration = MIN_DURATION
        print(f"  Padded audio to {MIN_DURATION:.0f}s", file=sys.stderr)

    composited = tmp_dir / "short_composited.mp4"

    if clip_paths:
        # Fast-cut montage: a new clip every ~3.5s at NORMAL speed (no 4× slowdown).
        bg_video  = build_montage_bg(clip_paths, short_duration, tmp_dir)
        host_pngs = prepare_host_pngs(tmp_dir)

        if host_pngs:
            # Presenter host (bottom-right) over the moving montage, gentle drift so
            # it's never a frozen still; SEQUENCE poses every SLOT sec (jump-cut between
            # the same person's poses). Then branding/CTA on top.
            N, SLOT = len(host_pngs), 5.0
            drift = "x='W-w-16+5*sin(2*t)':y='H-h+4*sin(1.3*t)'"
            inputs = ["-i", str(bg_video)]
            for hp in host_pngs:
                inputs += ["-loop", "1", "-i", str(hp)]
            inputs += ["-i", str(overlay_path)]
            fc, cur = [], "0:v"
            for k in range(N):
                en = f":enable='eq(mod(floor(t/{SLOT}),{N}),{k})'" if N > 1 else ""
                nxt = f"h{k}"
                fc.append(f"[{cur}][{k + 1}:v]overlay={drift}{en}[{nxt}]")
                cur = nxt
            fc.append(f"[{cur}][{N + 1}:v]overlay=0:0[out]")
            subprocess.run([
                "ffmpeg", "-y", *inputs,
                "-filter_complex", ";".join(fc),
                "-map", "[out]", "-t", f"{short_duration:.2f}",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-pix_fmt", "yuv420p", "-an", str(composited),
            ], check=True, stdout=subprocess.DEVNULL)
        else:
            # Static overlay (branding/title/CTA) on top of the moving montage
            subprocess.run([
                "ffmpeg", "-y",
                "-i", str(bg_video), "-i", str(overlay_path),
                "-filter_complex", "[0:v][1:v]overlay=0:0[out]",
                "-map", "[out]", "-t", f"{short_duration:.2f}",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-pix_fmt", "yuv420p", "-an", str(composited),
            ], check=True, stdout=subprocess.DEVNULL)
    else:
        # Fallback: static overlay only (no clips matched)
        subprocess.run([
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(overlay_path),
            "-t", f"{short_duration:.2f}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-an", str(composited),
        ], check=True, stdout=subprocess.DEVNULL)

    # ── Opening hook card + kinetic captions (word-synced, hype color-pop) ──
    # Best-effort: any failure ships the composited video without overlays.
    short_video = composited
    try:
        words = transcribe_words(short_audio)
        # Hook card owns the opening clause (until the first real pause), clamped 1.8–3.5s.
        hook_end = 2.5
        if words:
            hook_end = words[0][2]
            for i in range(len(words) - 1):
                if words[i + 1][1] - words[i][2] > 0.35:
                    hook_end = words[i][2]; break
                hook_end = words[i + 1][2]
            hook_end = min(max(hook_end, 1.8), 3.5)
        hook_frames = render_hook_frames(short_title, hook_end, tmp_dir)
        cap_words   = [w for w in words if w[1] >= hook_end - 0.05]
        overlays    = hook_frames + build_caption_pngs(cap_words, tmp_dir)
        if overlays:
            captioned = tmp_dir / "short_silent.mp4"
            burn_captions(composited, overlays, short_duration, captioned)
            short_video = captioned
            print(f"  Hook + captions burned ({len(overlays)} overlays, hook {hook_end:.1f}s)",
                  file=sys.stderr)
    except Exception as e:
        print(f"  [overlays] failed ({e}); shipping without hook/captions", file=sys.stderr)
        short_video = composited

    # Mux audio
    out_path = tmp_dir / "short_final.mp4"
    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(short_video), "-i", str(short_audio),
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
        str(out_path),
    ], check=True, stdout=subprocess.DEVNULL)

    kind = f"{len(clip_paths)} clips, fast-cut" if clip_paths else "static"
    print(f"  Short video built ({short_duration:.0f}s, {kind})", file=sys.stderr)
    return out_path


TRIVIA_COUNTDOWN = 2.5  # short — long silent countdowns tank retention (quiz avg was 38%)


def fetch_signal_readings():
    """Today's MarketPhase model reading (phase, score, per-indicator) — OUR original
    data, the one thing no other channel has. Best-effort; returns None on failure."""
    try:
        req = urllib.request.Request(
            "https://www.market-phase.com/api/market/signals",
            headers={"User-Agent": "Mozilla/5.0 (compatible; MarketPhase/1.0)"})
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read())
        print(f"  [signals] phase={d.get('phase')} score={d.get('score')}", file=sys.stderr)
        return d
    except Exception as e:
        print(f"  [signals] fetch failed ({e})", file=sys.stderr)
        return None


def call_claude_signals(readings: dict, today_display: str) -> dict:
    """Scriptwriter for a Short that reports TODAY's proprietary model reading — the
    differentiation play (original data, not a rewrite of everyone's news)."""
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set")
    phase = readings.get("phase", "")
    score = readings.get("score", "?")
    bd = "\n".join(f"- {b.get('indicator')}: {b.get('value')}"
                   for b in readings.get("scoreBreakdown", []))
    prompt = f"""You are a scriptwriter for "Tech Me Home", a finance channel by MarketPhase.
Today is {today_display}. Below is OUR proprietary market-timing model's reading RIGHT NOW —
original data no other channel has. Report it like an insider sharing a signal.

MODEL VERDICT: {phase}  (score {score} / 6)
Live indicator readings:
{bd}

Phase → action rules (use the one matching the verdict):
- Phase 1 / Green (score ≥5): hold longs, buy dips aggressively.
- Phase 2-3 / Watch (score 3-4): reduce risk, tighten stops, no new longs.
- Phase 4 / Red (score ≤2): exit growth positions, raise cash.

Write a 55-60 second YouTube Short. Output JSON with exactly:

1. "short_title": max 60 chars, no hashtags. Lead with the model's verdict + a stake.
   e.g. "My Model Just Hit Phase 2 — Here's the Play".

2. "short_hook": a 150-180 word spoken script (count carefully). RULES:
   - FIRST 5 WORDS: the model's verdict as a personal-stakes hook.
     e.g. "My market model just flipped." / "Score: four out of six."
   - State the phase and score plainly, then what it means for the viewer's money using
     the matching action rule above.
   - Cite 2-3 of the ACTUAL indicator readings above as evidence (name them: SOX/QQQ,
     VIX structure, breadth, CFNAI, jobless claims).
   - Tone: confident, insider, data-driven — you run a MODEL, not opinions. No generic panic.
   - End with exactly: "Subscribe so tomorrow's biggest move hits your feed first."
   - No stage cues, no "hey", no intro. Pure spoken words. MINIMUM 150 WORDS.

3. "clip_tags": ordered array of 4-6 tags for the montage, ONLY from:
   stock_bull, stock_crash, federal_reserve, wall_street, inflation,
   tech_stocks, earnings, nyse_open, data_screens, global_economy

4. "tags": 8-10 tags (no #), always incl "finance","markets","investing","Shorts".

Return ONLY valid JSON. No markdown."""
    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001", "max_tokens": 1200,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=payload,
        headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"}, method="POST")
    with urlopen_with_retry(req, timeout=90) as resp:
        result = json.loads(resp.read())
    raw = result["content"][0]["text"].strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw); raw = re.sub(r'\s*```$', '', raw)
    start = raw.find('{')
    if start != -1:
        raw = raw[start:]
    dec = json.JSONDecoder()
    try:
        obj, _ = dec.raw_decode(raw)
    except json.JSONDecodeError:
        obj, _ = dec.raw_decode(re.sub(r',\s*([}\]])', r'\1', raw))
    return obj


def call_claude_trivia(digest_summary: str, today_display: str, headlines=None) -> dict:
    """Generate a 3-question 'Guess the X' finance quiz from today's news + evergreen."""
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set")
    hl_block = ""
    if headlines:
        hl_block = ("\n\nTODAY'S RAW HEADLINES (base the news question on a SPECIFIC named "
                    "company/person/asset):\n" + "\n".join(f"- {h}" for h in headlines[:25]))
    prompt = f"""You are a YouTube Shorts quiz writer for "Tech Me Home", a finance channel by MarketPhase.
Today is {today_display}. Today's market news:

{digest_summary}{hl_block}

Write an interactive "Only 1% can pass this" style finance quiz. Output JSON with exactly:

1. "hook": one punchy line to open (e.g. "Only 1% of investors can ace today's market quiz.").
2. "short_title": Shorts title, max 60 chars, curiosity-driven, no hashtags.
3. "questions": array of EXACTLY 3 objects, progressively harder:
   - Q1 easy, Q2 medium, Q3 hard.
   - MIX: at least one tied to TODAY's news above, at least one evergreen finance concept.
   - Each: {{"q": "question text (max ~90 chars)",
             "choices": ["A text","B text","C text"]  (EXACTLY 3, each ≤ 4 words),
             "answer_idx": 0/1/2,
             "explain": "one short sentence why (max ~90 chars)"}}
   - Questions must be SELF-CONTAINED and answerable from public knowledge — never
     reference "the digest" or "today's summary". Verifiably correct answers only.
4. "outro": one line pushing a comment (e.g. "Comment your score below — be honest!").
5. "clip_tags": ordered array of 4-6 tags for the background montage, ONLY from:
   stock_bull, stock_crash, federal_reserve, wall_street, inflation,
   tech_stocks, earnings, nyse_open, data_screens, global_economy
6. "tags": 8-10 YouTube tags (no #). Always include "finance","markets","quiz","Shorts".

Return ONLY valid JSON. No markdown."""
    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1500,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=payload,
        headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"}, method="POST")
    with urlopen_with_retry(req, timeout=90) as resp:
        result = json.loads(resp.read())
    raw = result["content"][0]["text"].strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw); raw = re.sub(r'\s*```$', '', raw)
    start = raw.find('{')
    if start != -1:
        raw = raw[start:]
    dec = json.JSONDecoder()
    try:
        obj, _ = dec.raw_decode(raw)
    except json.JSONDecodeError:
        obj, _ = dec.raw_decode(re.sub(r',\s*([}\]])', r'\1', raw))
    return obj


def _trivia_canvas():
    """Dark full-frame canvas (montage faintly behind) with MARKET QUIZ branding."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (SHORT_W, SHORT_H), (8, 12, 24, 190))
    d   = ImageDraw.Draw(img)
    d.rectangle([(0, 0), (SHORT_W, 8)], fill=(29, 78, 216, 255))
    bf  = get_font(40, bold=True)
    d.text((40, 42), "MARKET", font=bf, fill=(255, 255, 255, 255))
    mw = d.textlength("MARKET", font=bf)
    d.text((40 + mw, 42), "QUIZ", font=bf, fill=(96, 165, 250, 255))
    d.rectangle([(0, SHORT_H - 8), (SHORT_W, SHORT_H)], fill=(239, 68, 68, 255))
    return img, d


def _wrap_text(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _draw_question(d, meta, highlight=None, explain=None):
    """Draw QUESTION label + wrapped question + 3 choice rows (+optional reveal)."""
    label_f = get_font(46, bold=True)
    q_f     = get_font(58, bold=True)
    c_f     = get_font(50, bold=True)
    e_f     = get_font(40, bold=True)
    draw_outlined_text(d, (60, 150), f"QUESTION {meta['n']} / 3", label_f,
                       (96, 165, 250, 255), thickness=4)
    y = 250
    for line in _wrap_text(d, meta["q"], q_f, SHORT_W - 120):
        draw_outlined_text(d, (60, y), line, q_f, (255, 255, 255, 255), thickness=5)
        y += 74
    cy = max(y + 50, 820)
    for j, c in enumerate(meta["choices"]):
        if highlight is None:
            box, col = (30, 41, 59, 235), (255, 255, 255, 255)
        elif j == highlight:
            box, col = (5, 150, 105, 255), (255, 255, 255, 255)    # correct = green
        else:
            box, col = (30, 41, 59, 170), (148, 163, 184, 255)     # wrong = dim
        d.rounded_rectangle([(60, cy), (SHORT_W - 60, cy + 116)], radius=18, fill=box)
        draw_outlined_text(d, (90, cy + 26), chr(65 + j), c_f, (251, 191, 36, 255), thickness=3)
        draw_outlined_text(d, (200, cy + 26), str(c), c_f, col, thickness=3)
        cy += 140
    if explain:
        ey = cy + 24
        for line in _wrap_text(d, explain, e_f, SHORT_W - 120):
            draw_outlined_text(d, (60, ey), line, e_f, (226, 232, 240, 255), thickness=3)
            ey += 52


def render_question_card(tmp_dir, k, meta, highlight=None, explain=None):
    img, d = _trivia_canvas()
    _draw_question(d, meta, highlight, explain)
    png = tmp_dir / f"tr_{k:03d}.png"; img.save(png, "PNG")
    return png


def render_countdown_frames(tmp_dir, k, meta, s, e):
    """Question card + shrinking bar + big ticking number over [s, e]."""
    import math
    dur   = e - s
    steps = max(1, int(round(dur / 0.25)))
    nf    = get_font(210, bold=True)
    frames, bar_max = [], SHORT_W - 160
    for i in range(steps):
        fs, fe    = s + i * (dur / steps), s + (i + 1) * (dur / steps)
        remaining = dur - i * (dur / steps)
        frac      = max(0.0, remaining / dur)
        num       = max(1, int(math.ceil(remaining)))
        img, d = _trivia_canvas()
        _draw_question(d, meta, highlight=None, explain=None)
        nt = str(num); nw = d.textlength(nt, font=nf)
        draw_outlined_text(d, (int((SHORT_W - nw) // 2), 1360), nt, nf,
                           (251, 191, 36, 255), thickness=8)
        bx, by, bh = 80, 1620, 46
        d.rounded_rectangle([(bx, by), (bx + bar_max, by + bh)], radius=23, fill=(30, 41, 59, 235))
        if frac > 0:
            d.rounded_rectangle([(bx, by), (bx + int(bar_max * frac), by + bh)],
                                radius=23, fill=(251, 191, 36, 255))
        png = tmp_dir / f"tr_{k + i:03d}.png"; img.save(png, "PNG")
        frames.append((png, round(fs, 2), round(fe, 2)))
    return frames


def render_text_card(tmp_dir, k, text, sub=None):
    img, d = _trivia_canvas()
    f = get_font(84, bold=True)
    lines = _wrap_text(d, text, f, SHORT_W - 140)
    y = (SHORT_H - len(lines) * 104) // 2
    for line in lines:
        lw = d.textlength(line, font=f)
        draw_outlined_text(d, (int((SHORT_W - lw) // 2), y), line, f,
                           (251, 191, 36, 255), thickness=7)
        y += 104
    if sub:
        sf = get_font(48, bold=True); sw = d.textlength(sub, font=sf)
        draw_outlined_text(d, (int((SHORT_W - sw) // 2), y + 40), sub, sf,
                           (255, 255, 255, 255), thickness=4)
    png = tmp_dir / f"tr_{k:03d}.png"; img.save(png, "PNG")
    return png


def generate_trivia_short(trivia: dict, clip_tags, tmp_dir: Path) -> Path:
    """Interactive quiz Short: hook → 3×(question → countdown → reveal) → outro."""
    hook      = trivia.get("hook", "Can you pass today's market quiz?")
    questions = (trivia.get("questions") or [])[:3]
    outro     = (trivia.get("outro", "Comment your score below!").rstrip(" .!")
                 + ". And subscribe for a fresh quiz every day.")
    if not questions:
        raise ValueError("trivia: no questions")

    # ── Normalize clip tags → clip paths (same rule as the narrative Short) ──
    if isinstance(clip_tags, str):
        clip_tags = [clip_tags]
    clip_paths = []
    for t in (clip_tags or []):
        p = get_clip_for_slide(t) if t else None
        if p and (not clip_paths or clip_paths[-1] != p):
            clip_paths.append(p)

    # ── 1. Build the audio timeline (TTS segments + countdown silences) ──
    audio_parts, timeline, t = [], [], 0.0

    def add_audio(path):
        nonlocal t
        d = get_audio_duration(path); s = t; t += d; audio_parts.append(str(path))
        return s, t

    def add_silence(dur):
        nonlocal t
        sp = tmp_dir / f"tr_sil_{len(audio_parts)}.mp3"
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                        "-t", f"{dur:.2f}", "-c:a", "libmp3lame", "-b:a", "192k", str(sp)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        s = t; t += dur; audio_parts.append(str(sp)); return s, t

    hook_mp3 = tmp_dir / "tr_hook.mp3"; tts_elevenlabs(hook, hook_mp3)
    s, e = add_audio(hook_mp3); timeline.append(("hook", {"text": hook}, s, e))

    for qi, q in enumerate(questions):
        choices = [str(c) for c in q.get("choices", [])][:3]
        ai      = int(q.get("answer_idx", 0)) % max(1, len(choices))
        meta    = {"q": q.get("q", ""), "choices": choices, "n": qi + 1,
                   "answer": ai, "explain": q.get("explain", "")}
        read = (f"Question {qi + 1}. {meta['q']} Is it: "
                + " ".join(f"{chr(65 + j)}: {c}." for j, c in enumerate(choices)))
        qmp3 = tmp_dir / f"tr_q{qi}.mp3"; tts_elevenlabs(read, qmp3)
        s, e = add_audio(qmp3);  timeline.append(("question", meta, s, e))
        s, e = add_silence(TRIVIA_COUNTDOWN); timeline.append(("countdown", meta, s, e))
        ans  = f"The answer is {chr(65 + ai)}. {meta['explain']}"
        amp3 = tmp_dir / f"tr_a{qi}.mp3"; tts_elevenlabs(ans, amp3)
        s, e = add_audio(amp3);  timeline.append(("reveal", meta, s, e))

    outro_mp3 = tmp_dir / "tr_outro.mp3"; tts_elevenlabs(outro, outro_mp3)
    s, e = add_audio(outro_mp3); timeline.append(("outro", {"text": outro}, s, e))
    total = t

    # Concat the full narration
    full_audio = tmp_dir / "tr_audio.mp3"
    lf = tmp_dir / "tr_audio.txt"; lf.write_text("\n".join(f"file '{p}'" for p in audio_parts))
    # Re-encode to a uniform rate (TTS chunks + silence may differ) → clean mux.
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lf),
                    "-ar", "44100", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "192k",
                    str(full_audio)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # ── 2. Background montage (or solid dark fallback) ──
    if clip_paths:
        bg_video = build_montage_bg(clip_paths, total, tmp_dir)
    else:
        bg_video = tmp_dir / "tr_bg.mp4"
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi",
                        "-i", f"color=c=0x0a0f1e:s={SHORT_W}x{SHORT_H}:r=30",
                        "-t", f"{total:.2f}", "-c:v", "libx264", "-preset", "fast",
                        "-crf", "23", "-pix_fmt", "yuv420p", str(bg_video)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # ── 3. Timed overlays from the timeline ──
    overlays, k = [], 0
    for kind, meta, s, e in timeline:
        if kind == "hook":
            overlays.append((render_text_card(tmp_dir, k, meta["text"]), s, e)); k += 1
        elif kind == "question":
            overlays.append((render_question_card(tmp_dir, k, meta), s, e)); k += 1
        elif kind == "countdown":
            fr = render_countdown_frames(tmp_dir, k, meta, s, e); overlays += fr; k += len(fr)
        elif kind == "reveal":
            overlays.append((render_question_card(tmp_dir, k, meta,
                             highlight=meta["answer"], explain=meta["explain"]), s, e)); k += 1
        elif kind == "outro":
            overlays.append((render_text_card(tmp_dir, k, meta["text"],
                             sub="SUBSCRIBE for a daily quiz"), s, e)); k += 1

    # ── 4. Burn overlays over the montage, then mux audio ──
    silent = tmp_dir / "tr_silent.mp4"
    burn_captions(bg_video, overlays, total, silent)
    out_path = tmp_dir / "trivia_final.mp4"
    subprocess.run(["ffmpeg", "-y", "-i", str(silent), "-i", str(full_audio),
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(out_path)],
                   check=True, stdout=subprocess.DEVNULL)
    print(f"  Trivia short built ({total:.0f}s, {len(questions)} questions, "
          f"{len(overlays)} overlays)", file=sys.stderr)
    return out_path


def upload_short_to_youtube(short_path: Path, short_title: str,
                            main_video_title: str, description_override: str = None) -> str:
    """Upload a YouTube Short — vertical, under 60 sec, with #Shorts tag."""
    access_token = get_youtube_access_token()
    today_str    = date.today().strftime("%B %d, %Y")

    description = description_override or (
        f"💥 {main_video_title}\n\n"
        f"Watch the full breakdown 👉 {SITE_URL}\n\n"
        f"New market shorts every weekday. Follow for daily insights.\n\n"
        f"📅 {today_str}\n\n"
        f"#Shorts #finance #markets #investing #stocks #money #MarketPhase"
    )

    metadata = json.dumps({
        "snippet": {
            "title": f"{short_title} #Shorts",
            "description": description[:5000],
            "tags": ["Shorts", "finance", "markets", "investing", "stocks",
                     "money", "MarketPhase", "financial news", "market update"],
            "categoryId": "25",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        }
    }).encode()

    boundary   = "==marketphase_short_boundary=="
    video_bytes = short_path.read_bytes()
    body = (
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
    ).encode() + metadata + (
        f"\r\n--{boundary}\r\nContent-Type: video/mp4\r\n\r\n"
    ).encode() + video_bytes + f"\r\n--{boundary}--".encode()

    req = urllib.request.Request(
        "https://www.googleapis.com/upload/youtube/v3/videos"
        "?uploadType=multipart&part=snippet,status",
        data=body,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": f"multipart/related; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read())

    short_id  = result["id"]
    short_url = f"https://www.youtube.com/shorts/{short_id}"
    print(f"  Short uploaded: {short_url}", file=sys.stderr)
    return short_url


# ── YouTube Analytics ─────────────────────────────────────────────────────────

def fetch_and_save_analytics(repo_root: Path):
    """Fetch last 30 days of per-video analytics + titles, save to finance-hub/analytics.json."""
    try:
        access_token = get_youtube_access_token()
        today = date.today().isoformat()
        start = date.fromordinal(date.today().toordinal() - 30).isoformat()

        # 1. Analytics metrics per video (incl. averageViewPercentage = retention)
        req = urllib.request.Request(
            f"https://youtubeanalytics.googleapis.com/v2/reports"
            f"?ids=channel%3D%3DMINE&startDate={start}&endDate={today}"
            f"&metrics=views,estimatedMinutesWatched,averageViewDuration,"
            f"averageViewPercentage,subscribersGained"
            f"&dimensions=video&sort=-views&maxResults=30",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        with urlopen_with_retry(req, timeout=60) as resp:
            analytics = json.loads(resp.read())

        rows = analytics.get("rows", [])
        if not rows:
            print("  Analytics: no data yet", file=sys.stderr)
            return

        # 2. Titles via public oEmbed — the youtube.upload scope can't read
        #    videos.list (403), so don't gate the whole save on it.
        def _title(vid):
            try:
                u = (f"https://www.youtube.com/oembed?format=json"
                     f"&url=https://www.youtube.com/watch?v={vid}")
                with urlopen_with_retry(urllib.request.Request(u), timeout=20) as r2:
                    return json.loads(r2.read()).get("title", vid)
            except Exception:
                return vid
        titles = {r[0]: _title(r[0]) for r in rows}

        # 3. Build enriched video list
        videos = []
        for r in rows:
            vid_id = r[0]
            videos.append({
                "id":                 vid_id,
                "title":              titles.get(vid_id, vid_id),
                "url":                f"https://www.youtube.com/watch?v={vid_id}",
                "views":              r[1],
                "watchMinutes":       r[2],
                "avgViewDuration":    r[3],
                "avgViewPercentage":  r[4],
                "subscribersGained":  r[5],
            })

        totals = {
            "views":             sum(v["views"] for v in videos),
            "watchMinutes":      sum(v["watchMinutes"] for v in videos),
            "subscribersGained": sum(v["subscribersGained"] for v in videos),
        }

        out = repo_root / "finance-hub" / "analytics.json"
        out.write_text(json.dumps({
            "updated": today,
            "period": f"{start} → {today}",
            "videos": videos,
            "totals": totals,
        }, indent=2), encoding="utf-8")
        print(f"  Analytics saved → {out.name} ({len(videos)} videos)", file=sys.stderr)
    except Exception as e:
        detail = ""
        if hasattr(e, "read"):
            try:
                detail = e.read().decode("utf-8", "ignore")[:400]
            except Exception:
                pass
        code = getattr(e, "code", "")
        print(f"  Analytics fetch failed (non-fatal): {code} {e} {detail}", file=sys.stderr)
        if str(code) == "403":
            print("  → HTTP 403: the OAuth token likely lacks the yt-analytics.readonly "
                  "scope. Re-run `python scripts/get_youtube_token.py`, update the "
                  "YOUTUBE_REFRESH_TOKEN secret, and ensure the YouTube Analytics API is "
                  "enabled in your Google Cloud project.", file=sys.stderr)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    today = date.today()
    today_display = today.strftime("%A, %B %-d, %Y")

    # Mode detection (priority order):
    #   SHORTS_ONLY=true  → Short only, lean Claude prompt, skip long video entirely
    #   SCRIPT_FILE=...   → Long video from pre-written script + Short
    #   TOPIC=...         → Long video on specific topic + Short
    #   (default)         → Long video from daily digest + Short
    SHORTS_ONLY = os.environ.get("SHORTS_ONLY", "").strip().lower() in ("1", "true", "yes")
    SCRIPT_FILE = os.environ.get("SCRIPT_FILE", "").strip()
    TOPIC       = os.environ.get("TOPIC", "").strip()

    ensure_deps()
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    # ── SHORTS-ONLY path ──────────────────────────────────────────────────────
    if SHORTS_ONLY:
        # Rotating content: signals (OUR data) / narrative (news) / interactive trivia.
        # SHORT_TYPE = auto (default) | signals | narrative | trivia. auto → 3-way by date.
        short_type = os.environ.get("SHORT_TYPE", "auto").strip().lower()
        if short_type not in ("signals", "narrative", "trivia"):
            short_type = ["signals", "narrative", "trivia"][date.today().toordinal() % 3]

        print(f"=== Daily Short [{short_type}] — {today_display} ===", file=sys.stderr)
        print("Reading digest…", file=sys.stderr)
        digest_summary = read_today_digest()
        print("Fetching hot headlines…", file=sys.stderr)
        headlines = fetch_hot_headlines()

        if short_type == "trivia":
            print("Generating trivia quiz with Claude…", file=sys.stderr)
            data        = call_claude_trivia(digest_summary, today_display, headlines)
            short_title = (data.get("short_title") or f"Market Quiz {today.strftime('%b %d')}").strip()
            clip_tags   = data.get("clip_tags")
            print(f"  Title: {short_title} | {len(data.get('questions', []))} questions", file=sys.stderr)
            print("Generating trivia Short…", file=sys.stderr)
            short_path = generate_trivia_short(data, clip_tags, TMP_DIR)
            desc = ("Can you pass today's market quiz? Comment your score below 👇\n\n"
                    "New finance quiz & market shorts every weekday. Follow for daily insights.\n\n"
                    "#Shorts #finance #markets #quiz #investing #stocks #MarketPhase")
            short_url = upload_short_to_youtube(short_path, short_title,
                                                f"MarketPhase Quiz — {today_display}",
                                                description_override=desc)
        else:
            # signals (our model reading) and narrative (news) both render as a Short.
            if short_type == "signals":
                readings = fetch_signal_readings()
                if readings:
                    print("Generating signals script with Claude…", file=sys.stderr)
                    data = call_claude_signals(readings, today_display)
                else:
                    print("  [signals] no readings — falling back to narrative", file=sys.stderr)
                    short_type = "narrative"
            if short_type == "narrative":
                print("Generating Short script with Claude…", file=sys.stderr)
                data = call_claude_short(digest_summary, today_display, headlines)
            short_hook  = data.get("short_hook", "")
            short_title = data.get("short_title", f"Market Update {today.strftime('%b %d')}").strip()
            clip_tags   = data.get("clip_tags") or data.get("clip_tag")
            if not short_hook:
                print("ERROR: Claude returned no short_hook", file=sys.stderr)
                sys.exit(1)
            print(f"  Title: {short_title}", file=sys.stderr)
            print(f"  Hook:  {short_hook[:80]}…", file=sys.stderr)
            print("Generating YouTube Short…", file=sys.stderr)
            short_path = generate_short_video(short_hook, short_title, clip_tags, TMP_DIR)
            if short_type == "signals":
                desc = ("Today's reading from our market-timing model. See the live dashboard → "
                        "https://www.market-phase.com/signals\n\n"
                        "New market shorts every weekday. Subscribe for the daily signal.\n\n"
                        "#Shorts #finance #markets #investing #stocks #MarketPhase")
                short_url = upload_short_to_youtube(short_path, short_title,
                            f"MarketPhase Signal — {today_display}", description_override=desc)
            else:
                short_url = upload_short_to_youtube(short_path, short_title,
                            f"MarketPhase Daily — {today_display}")

        print(f"\n✅ Short live [{short_type}]: {short_url}", file=sys.stderr)
        print("Fetching analytics…", file=sys.stderr)
        fetch_and_save_analytics(REPO_ROOT)
        return

    # ── LONG VIDEO path (on-demand or manual trigger) ─────────────────────────
    if SCRIPT_FILE:
        print(f"=== Custom Script Video — {today_display} ===", file=sys.stderr)
        print(f"    Script: {SCRIPT_FILE}", file=sys.stderr)
    elif TOPIC:
        print(f"=== On-Demand Topic Video — {today_display} ===", file=sys.stderr)
        print(f"    Topic: {TOPIC}", file=sys.stderr)
    else:
        print(f"=== Daily Long Video — {today_display} ===", file=sys.stderr)

    # 1. Generate script + slide data
    print("Generating script + slides with Claude…", file=sys.stderr)
    if SCRIPT_FILE:
        is_path = len(SCRIPT_FILE) < 500 and "\n" not in SCRIPT_FILE
        if is_path:
            script_path = Path(SCRIPT_FILE)
            if not script_path.exists():
                print(f"ERROR: Script file not found: {SCRIPT_FILE}", file=sys.stderr)
                sys.exit(1)
            custom_narration = script_path.read_text(encoding="utf-8").strip()
            print(f"  Loaded {len(custom_narration.split())} words from {SCRIPT_FILE}", file=sys.stderr)
        else:
            custom_narration = SCRIPT_FILE.strip()
            print(f"  Using inline script ({len(custom_narration.split())} words)", file=sys.stderr)
        data = call_claude_from_script(custom_narration, today_display)
    elif TOPIC:
        data = call_claude_topic(TOPIC, today_display)
    else:
        print("Reading digest…", file=sys.stderr)
        digest_summary = read_today_digest()
        data = call_claude(digest_summary, today_display)

    narration_script = data["narration"]
    slides_data      = data["slides"]
    video_title  = data.get("title",       f"Market Update {today.strftime('%b %d, %Y')}").strip()
    short_title  = data.get("short_title", video_title[:60]).strip()
    short_hook   = data.get("short_hook",  "")
    chapters     = data.get("chapters",    [])
    extra_tags   = data.get("tags",        [])
    print(f"  Title:  {video_title}", file=sys.stderr)
    print(f"  Short:  {short_title}", file=sys.stderr)
    print(f"  Script: {len(narration_script.split())} words, {len(slides_data)} slides", file=sys.stderr)

    # 2. TTS narration
    print("Generating voiceover with ElevenLabs…", file=sys.stderr)
    narration_clean = strip_cues(narration_script)
    audio_path = TMP_DIR / "narration.mp3"
    tts_elevenlabs(narration_clean, audio_path)

    # 3. Slide durations + rendering
    audio_duration = get_audio_duration(audio_path)
    durations   = calc_slide_durations(slides_data, audio_duration)
    print("Creating slides…", file=sys.stderr)
    slide_paths = create_slides(slides_data, durations, TMP_DIR)

    # 4. Build long MP4
    print("Building video…", file=sys.stderr)
    video_path = TMP_DIR / f"marketphase_{today.isoformat()}.mp4"
    build_video(slide_paths, audio_path, video_path)

    # 5. Thumbnail
    print("Generating thumbnail…", file=sys.stderr)
    thumb_tag     = slides_data[0].get("clip_tag") if slides_data else None
    thumb_keyword = slides_data[0].get("pexels_keyword", "stock market finance") if slides_data else "stock market"
    if thumb_tag:
        thumb_keyword = thumb_tag.replace("_", " ")
    thumbnail_path = generate_thumbnail(video_title, thumb_keyword, TMP_DIR)

    # 6. Upload long video
    print("Uploading main video to YouTube…", file=sys.stderr)
    hook_lines = [l.strip() for l in narration_script.split('\n')
                  if l.strip() and not l.strip().startswith('[')][:3]
    hook_text = " ".join(hook_lines)[:300]
    url = upload_to_youtube(video_path, video_title, hook_text,
                            thumbnail_path, chapters, extra_tags)

    # 7. Short (derived from long video data)
    if short_hook:
        print("Generating YouTube Short…", file=sys.stderr)
        # Shot-list for the fast-cut Short = every slide's clip tag, in order.
        short_clip_tags = [s.get("clip_tag") for s in slides_data if s.get("clip_tag")] \
            if slides_data else []
        try:
            short_path = generate_short_video(short_hook, short_title,
                                              short_clip_tags, TMP_DIR)
            short_url  = upload_short_to_youtube(short_path, short_title, video_title)
            print(f"  Short: {short_url}", file=sys.stderr)
        except Exception as e:
            print(f"  Short failed (non-fatal): {e}", file=sys.stderr)

    # 8. Analytics
    print("Fetching analytics…", file=sys.stderr)
    fetch_and_save_analytics(REPO_ROOT)

    print(f"\n✅ Done! Watch at: {url}", file=sys.stderr)


if __name__ == "__main__":
    main()
