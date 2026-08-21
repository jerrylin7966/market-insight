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

## 📊 CHECKPOINT RESULT — 2026-08-20 (entity-topics did NOT fix reach)
Pulled 28d analytics: **channel 255 views / 2 subs / 100 watch-min (~9 views/day — STALLED).** New entity-driven videos have great retention but near-zero reach: BofA-Nvidia 82%/6v, Cisco 100%/1v, Fink 1v, Warsh 1v. **Engagement = 0 comments / ~0 likes across everything (incl. trivia).** Conclusion: production (hook/captions/v3), script (high-arousal/entity), and format (trivia) are ALL tested — retention proves they work, but NONE moved reach. **The bottleneck is distribution + zero engagement, not code.** More automation tweaks = low expected value.
Also: off-topic uploads diluting the niche ("2026最多人下載的AI工具", "Here you go…", bare "#geopolitics #iran") — must be finance-only.

## ⏳ TODO / Next (reprioritized — distribution/strategy over production)
- [ ] **#1 Engagement seeding (manual, biggest lever):** seed first comment + reply/pin on each upload; 0 comments is starving distribution.
- [ ] **#2 Topical discipline:** stop/remove off-topic uploads; finance-only.
- [ ] **#3 External seeding:** drive 30–50 initial views/upload from market-phase.com + X + Reddit finance subs to break the chicken-and-egg.
- [x] **#4 (code) `/signals`-data content mode** — SHIPPED (commit 4d57c9e). `fetch_signal_readings` (live `/api/market/signals` → phase/score/indicators) + `call_claude_signals` → data-driven Short reporting today's model verdict. Rotation now **3-way** (`SHORT_TYPE=auto` → signals/narrative/trivia by `date%3`). Differentiation play.
- [x] **#5 (code) human/character element** — SHIPPED (commit f6c3eeb). ONE real host (host_1+host_2 = same person, 2 poses), green-screen removed + despilled, presenter over montage, **sequencing poses every 5s**; thumbnail pinned to host_1. Narrative + signals Shorts only (not trivia).
- [ ] **STILL ON USER (not code, the real levers):** #1 engagement seeding (comment/reply/pin), #2 topical discipline (finance-only; kill off-topic uploads), #3 external seeding (30–50 initial views/upload). Production is done; distribution is the ceiling.
- [ ] Source even hotter / trending topics if entity-sourcing under-delivers.
- [ ] Dead RSS feed: `feeds.reuters.com` (DNS fail) — replace or drop from `_HEADLINE_FEEDS` / digest `FEEDS`.

## ⚠️ Gotchas
- **Burned PIL text must be ASCII** — DejaVu Bold on the runner renders `▶`/emoji as tofu boxes (was visible on live videos). Emoji is fine only in YouTube **description** strings.
- `.html` local-test note: code uses `X | None` (py3.10+); base python may be 3.9 — import a temp copy with `from __future__ import annotations` prepended for local tests. Stub `tts_elevenlabs`; macOS `say` makes real speech for whisper tests.
