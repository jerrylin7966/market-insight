# AdSense Approval — Diagnosis & Progress (market-phase.com)

_Last updated: 2026-08-12. Review locked until **Aug 19, 2026** (attempt limit reached)._

## 🔑 Core diagnostic insight
AdSense rejected the site for **"Low value content"** — a **content-quality** verdict, **NOT** a timing / "too new / not indexed" problem. Requesting later would not have changed it.

**Root cause:** the **66 daily digests are AI-edited summaries of other outlets' articles** — textbook *scaled / low-value content* (rewritten aggregated news, no original reporting). Per GSC (Aug 12), **~30 of them were indexed — roughly half the site's indexed footprint** — so they materially dragged the site's quality profile.

**What is NOT the problem (don't get distracted):** the scary "106 not indexed" on the domain property is **~80% redirect/canonical noise** from the Aug-8 `.html`→www consolidation still reprocessing (`Page with redirect` 45 + `Alternate page w/ canonical` 35). That clears on its own. The real quality signal is small (`Discovered/Crawled – not indexed` ≈ 25).

**Honest caveat:** the site is AI-assisted **and** near-zero-traffic (5–94 impressions/day). That's a hard AdSense profile. The fixes below are **necessary but may not be sufficient** on one resubmit.

## ✅ Fixes shipped
- **noindex,follow on all 66 daily digests + the generator template** (`db33c87`). Kept the `/daily/` hub + 24 guides indexable. Digests stay live for users + the YouTube pipeline. → AdSense now evaluates the guides + signals, not the thin digests.
- **Enriched `/signals` with a 410-word framework-methodology section** (5 headings + 7 internal guide links) (`01da061`). Turns the site's genuinely unique asset (live SOX/QQQ + VIX term structure + CFNAI + breadth dashboard with a 6-point phase model) from a text-thin chart page into a content-rich, uniquely valuable one — the "original tool, not scaled text" signal AdSense rewards.
- (Earlier) redirect/canonical consolidation to clean www (`0edfb47`), E-E-A-T author wiring, disclaimers.

## 📌 Checkpoint — Aug 20
GSC Pages: Indexed still ~58 (www) / 104 (domain) — barely down. **"Excluded by 'noindex' tag" = 1 of 66** → the noindex has NOT propagated; ~30 digests still indexed. Redirect(60)/Alternate(35) buckets = intentional consolidation, ignore ("Page with redirect" validation will always "fail" — redirects are by design). `/signals` = "available to Google / can be indexed / indexing requested" (on track, not yet confirmed on Google). **DECISION: do NOT resubmit yet** — wait for "Excluded by noindex" to climb toward ~30 and Indexed to drop toward ~30 (guides+signals+core). Accelerator: Request-Index the still-indexed digest URLs to force recrawl→noindex→drop.

## 🔴 2nd rejection + THE REAL FIX (Aug 29)
Resubmitted after Aug 19 → **rejected again, "Low value content."** Reconciliation: **noindex removes pages from Google SEARCH, but AdSense reviews the LIVE site** — the 75 AI-digests were still nav-linked + indexed. GSC Aug-29 proved noindex failed: only **1 of 75** "excluded by noindex" after 17 days. Impressions rose to 100–140/day → guides/signals have real value; digests were the anchor.
**FIX SHIPPED (ffe2962, c7b946e):** digests **REMOVED from the public site**, not just noindexed — (1) digest gen repointed to PRIVATE `daily_data/` (gitignored, not deployed) so the YouTube pipeline still reads it; `read_today_digest` updated; (2) deleted 75 digest pages + `/daily/` hub; stripped "Daily Digest" from nav/footer (30 pages) + 4 sidebar cards; (3) `_redirects`: `/daily/* → / 301` (live; was soft-404 via SPA fallback); (4) sitemap `/daily/` removed; workflow stops committing `finance-hub/daily/`. Site now = `/signals` + 24 guides + `/what-phase-is-the-market-in`. **Next: let Google recrawl (~1–2 wks) so /daily/ drops, then request review again.**

## ⏳ TODO before resubmitting (gated on deindex, not date)
- [ ] Let Google recrawl (~1 week) so the noindexed digests actually **drop from the index**. Confirm in GSC → Pages that `/daily/` dated URLs fall out of "Indexed".
- [ ] **Strengthen 3–5 flagship guides** with genuinely original analysis/data (not more AI filler) so the indexed footprint reads as human-quality.
- [ ] Optional: reciprocal **guide → `/signals` "see it live"** callouts (internal linking + reinforces the tool).
- [ ] Foreground `/signals` as the site's centerpiece (already signals-first in title/H1/nav).
- [ ] **Then** request review (Aug 19+).

## 🧭 If it's still "Low value content" after Aug 19
Stop mechanical tweaks. The durable levers are:
1. **Real traffic** — the YouTube channel ("Tech Me Home") is the natural driver.
2. **Depth + originality** on the guides + the signals tool (unique data/analysis a generic AI page can't produce).
3. Consider whether daily AI-aggregation belongs on the domain at all vs. an app/subdomain.
