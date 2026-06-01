#!/usr/bin/env python3
"""
inject_ads.py — Auto-inject AdSense publisher script, ads.js, and mobile-nav.js
into every HTML page under finance-hub/ that doesn't already have them.

Run automatically by GitHub Actions on every push that touches HTML files.
Can also be run locally: python scripts/inject_ads.py
"""

import sys
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────────
BASE = Path(__file__).parent.parent / "finance-hub"

ADSENSE_SCRIPT = (
    '<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js'
    '?client=ca-pub-5264064065432511" crossorigin="anonymous"></script>'
)

ADS_JS_TAG        = '<script src="/js/ads.js"></script>'
MOBILE_NAV_TAG    = '<script src="/js/mobile-nav.js"></script>'

# Pages that intentionally carry no ads
ADS_EXCLUDE = {
    "signals/index.html",
}

# Pages that have no <nav class="nav"> (no hamburger needed)
NAV_EXCLUDE = set()   # currently all pages have the nav — leave empty

# ── Helpers ────────────────────────────────────────────────────────────────

def needs_adsense(content: str) -> bool:
    return "ca-pub-5264064065432511" not in content

def needs_ads_js(content: str) -> bool:
    return ADS_JS_TAG not in content

def needs_mobile_nav(content: str) -> bool:
    # Only inject if the page actually has the nav markup
    return MOBILE_NAV_TAG not in content and ('class="nav"' in content or 'class="site-nav"' in content)

def inject_adsense(content: str) -> str:
    """Insert AdSense publisher script just before </head>."""
    return content.replace("</head>", f"{ADSENSE_SCRIPT}\n</head>", 1)

def inject_ads_js(content: str) -> str:
    """Insert ads.js script just before </body>."""
    return content.replace("</body>", f"{ADS_JS_TAG}\n</body>", 1)

def inject_mobile_nav(content: str) -> str:
    """Insert mobile-nav.js just before </body> (after ads.js if present)."""
    return content.replace("</body>", f"{MOBILE_NAV_TAG}\n</body>", 1)

# ── Main ───────────────────────────────────────────────────────────────────

def main():
    html_files = sorted(BASE.rglob("*.html"))
    changed = []
    skipped = []

    for path in html_files:
        rel = str(path.relative_to(BASE))

        content = path.read_text(encoding="utf-8")
        original = content
        injected = []

        # Ads (excluded for signals page)
        if rel not in ADS_EXCLUDE:
            if needs_adsense(content):
                content = inject_adsense(content)
                injected.append("AdSense script")
            if needs_ads_js(content):
                content = inject_ads_js(content)
                injected.append("ads.js")

        # Mobile nav (all pages with a nav bar)
        if rel not in NAV_EXCLUDE and needs_mobile_nav(content):
            content = inject_mobile_nav(content)
            injected.append("mobile-nav.js")

        if content != original:
            path.write_text(content, encoding="utf-8")
            changed.append((rel, injected))
        else:
            skipped.append(rel)

    # ── Report ──────────────────────────────────────────────────────────────
    if changed:
        print(f"Injected scripts into {len(changed)} file(s):")
        for rel, what in changed:
            print(f"  ✓ {rel}  ({', '.join(what)})")
    else:
        print("All HTML files already up to date — nothing to do.")

    return 0

if __name__ == "__main__":
    sys.exit(main())
