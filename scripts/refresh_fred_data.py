#!/usr/bin/env python3
"""
Fetch FRED data (IC4WSA + CFNAI) via FRED's public CSV export (no API key needed).
Run daily via GitHub Actions and commit as static JSON served by Cloudflare Pages.
"""

import csv, io, json, math, os, sys, urllib.request
from datetime import datetime
from pathlib import Path

OUT_DIR = Path(__file__).parent.parent / "finance-hub" / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://fred.stlouisfed.org/",
}


def fred_csv(series_id: str) -> list[dict]:
    """Fetch FRED series as CSV — no API key required."""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=25) as resp:
        text = resp.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for row in reader:
        try:
            val = float(row["VALUE"])
            if not math.isnan(val):
                rows.append({"date": row["DATE"], "value": val})
        except (ValueError, KeyError):
            pass
    return rows


def build_claims() -> dict:
    data = fred_csv("IC4WSA")
    if len(data) < 5:
        raise ValueError(f"Only {len(data)} IC4WSA rows — too few")
    # Keep last 104 weeks
    data = data[-104:]
    latest       = data[-1]["value"]
    previous     = data[-2]["value"]
    four_ago     = data[-5]["value"]
    is_improving = latest < four_ago
    return {
        "data":         data,
        "latest":       latest,
        "previous":     previous,
        "fourWeeksAgo": four_ago,
        "trend":        "Improving" if is_improving else "Worsening",
        "trendColor":   "green"     if is_improving else "red",
        "floorStatus":  (
            "Claims Decelerating — Floor Support ✅"
            if is_improving else
            "Claims Rising — Macro Risk ⚠"
        ),
        "fetchedAt": datetime.utcnow().isoformat() + "Z",
    }


def analyse_cfnai(ma3_series, raw_series) -> dict:
    latest = ma3_series[-1]
    v = latest["value"]
    if v > 0.20:
        signal, color, bullish = "Strong Expansion ↑", "green", True
    elif v > 0:
        signal, color, bullish = "Expanding ↑",        "green", True
    elif v > -0.70:
        signal, color, bullish = "Below Trend ↓",      "amber", False
    else:
        signal, color, bullish = "Recession Risk ↓",   "red",   False
    return {
        "ma3Series":     ma3_series,
        "rawSeries":     raw_series or [],
        "ma3Latest":     v,
        "ma3LatestDate": latest["date"][:7],
        "rawLatest":     raw_series[-1]["value"] if raw_series else None,
        "rawLatestDate": raw_series[-1]["date"][:7] if raw_series else None,
        "signal":    signal,
        "color":     color,
        "isBullish": bullish,
        "scored":    bullish,
        "source":    "FRED (CFNAI)",
        "fetchedAt": datetime.utcnow().isoformat() + "Z",
    }


def build_cfnai() -> dict:
    # Truncate dates to YYYY-MM for monthly series
    ma3 = [{"date": r["date"][:7], "value": r["value"]} for r in fred_csv("CFNAIMA3")]
    raw = [{"date": r["date"][:7], "value": r["value"]} for r in fred_csv("CFNAI")]
    if not ma3:
        raise ValueError("No CFNAIMA3 data")
    return analyse_cfnai(ma3, raw)


def main():
    errors = []

    print("Fetching IC4WSA (4-week MA initial claims)…")
    try:
        claims = build_claims()
        path = OUT_DIR / "claims.json"
        path.write_text(json.dumps(claims, separators=(",", ":")))
        latest_date = claims["data"][-1]["date"]
        print(f"  ✅ {len(claims['data'])} weeks, latest {latest_date} "
              f"= {claims['latest']:,.0f}  ({claims['trend']}) → {path.name}")
    except Exception as e:
        print(f"  ❌ Failed: {e}", file=sys.stderr)
        errors.append(str(e))

    print("Fetching CFNAI-MA3…")
    try:
        cfnai = build_cfnai()
        path = OUT_DIR / "cfnai.json"
        path.write_text(json.dumps(cfnai, separators=(",", ":")))
        print(f"  ✅ {cfnai['ma3LatestDate']} = {cfnai['ma3Latest']:.3f} "
              f"({cfnai['signal']}) → {path.name}")
    except Exception as e:
        print(f"  ❌ Failed: {e}", file=sys.stderr)
        errors.append(str(e))

    if errors:
        print(f"\n{len(errors)} error(s). FRED data unchanged.", file=sys.stderr)
        sys.exit(1)
    print("\nDone ✅")


if __name__ == "__main__":
    main()
