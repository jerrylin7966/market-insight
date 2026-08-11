# YouTube Shorts Pipeline — Progress & TODO

Channel **"Tech Me Home"** (by MarketPhase). Pipeline: `generate_daily_digest.py` → `generate_daily_video.py`, run by `.github/workflows/daily-digest.yml` (cron `30 10 * * 1-5`, `SHORTS_ONLY=true`). Scripts written by Anthropic Claude (`claude-haiku-4-5`); voice = ElevenLabs `eleven_v3`. Daily Short alternates by date parity: **narrative** (odd) / **trivia** (even) via `SHORT_TYPE=auto`.

_Last updated: 2026-08-11._

---

## ✅ Shipped

- **Fast-cut montage** — new clip every ~3.5s (replaced one clip slowed 4×).
- **ElevenLabs v3 voice** — `ELEVENLABS_MODEL` env, auto-falls back to `multilingual_v2`.
- **Kinetic word-synced captions** — hype color-pop, active word yellow; faster-whisper alignment; PIL PNGs burned via ffmpeg. Overlap-at-boundaries bug fixed (contiguous windows).
- **Animated opening hook card** — first ~2.5s is a big centered pop-in title over motion (killed the static-title-card swipe point), then hands off to captions.
- **High-arousal angle rotation** — money-at-risk / opportunity / contrarian-shock / insider / wallet (dropped soft "educational"); first-5-words hook mandate; high-stakes titles.
- **Entity-driven topic sourcing** — Short/trivia now pull fresh raw RSS headlines + a hard SUBJECT RULE: one named company/person/asset + a concrete number, never "the market". _(The #1 reach lever per the data.)_
- **Trivia countdown 4s → 2.5s** — the silent countdown was tanking quiz retention.
- **Stronger Subscribe CTA** — narrative red on-screen pill + reason-to-subscribe spoken end-line; trivia outro says + shows subscribe.
- **Interactive trivia format** — hook → 3×(question → countdown → green reveal) → outro.
- **Analytics** — user enabled YouTube Analytics API + re-authed token with `yt-analytics.readonly`; workflow now commits `finance-hub/analytics.json` (incl. `averageViewPercentage`); titles via public oEmbed (upload scope can't do `videos.list`).

## 📊 Key data finding (analytics pull, 90d / 50 videos, 2026-08-11)
- **Retention is GOOD** on recent videos (65–82%) → production works; the bottleneck is **reach + topic**, not swipe-away.
- **Winners = specific named entity + concrete number** (Microsoft's Worst Month Since 2000: 745 views / 83%; SpaceX $60B Secret: 1084 / 75%). **Losers = generic macro** (Market Rally Built on Sand: 105 / 13%).
- **Trivia retains worse** than narrative (quiz 38% vs 65–82%) — hence the countdown cut.
- **Sub conversion low**: 18 subs / 9077 views (0.2%) — hence the stronger CTA.

## ⏳ TODO / Next
- [ ] **Measurement checkpoint (~2026-08-25):** pull `analytics.json`; check whether new **entity-driven** videos get **more impressions/views at the same good retention**. That confirms whether topic sourcing fixed reach. _(Refresh-token → access-token → youtubeanalytics v2 `reports`, `ids=channel==MINE`, metrics incl. `averageViewPercentage`; titles via oEmbed.)_
- [ ] **Re-introduce a human/character element** — biggest untested lever vs the faceless-AI-slop risk (old human-host videos hit 90–285 views). **Hold** until the above checkpoint isolates the topic/hook effect first.
- [ ] Source even hotter / trending topics if entity-sourcing under-delivers.
- [ ] Dead RSS feed: `feeds.reuters.com` (DNS fail) — replace or drop from `_HEADLINE_FEEDS` / digest `FEEDS`.

## ⚠️ Gotchas
- **Burned PIL text must be ASCII** — DejaVu Bold on the runner renders `▶`/emoji as tofu boxes (was visible on live videos). Emoji is fine only in YouTube **description** strings.
- `.html` local-test note: code uses `X | None` (py3.10+); base python may be 3.9 — import a temp copy with `from __future__ import annotations` prepended for local tests. Stub `tts_elevenlabs`; macOS `say` makes real speech for whisper tests.
