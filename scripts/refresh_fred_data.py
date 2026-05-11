#!/usr/bin/env python3
"""
Fetch FRED data (IC4WSA + CFNAI) once daily via GitHub Actions
and save as static JSON files served by Cloudflare Pages.

This sidesteps FRED blocking Cloudflare Worker IP ranges.
"""

import json, math, os, sys, urllib.request
from datetime import date, datetime
from pathlib import Path

FRED_API_KEY = os.environ.get("FRED_API_KEY", "e2cb31396b55aa6b693a2e5d60c00faa")
OUT_DIR = Path(__file__).parent.parent / "finance-hub" / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def fred_fetch(series_id: str, limit: int = 200, sort: str = "asc") -> list:
    url = (
        f"https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={series_id}&api_key={FRED_API_KEY}&file_type=json"
        f"&sort_order={sort}&observation_start=2004-01-01&limit={limit}"
    )
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; MarketPhase/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = json.loads(resp.read())
    obs = body.get("observations", [])
    return [
        {"date": o["date"][:7] if len(o["date"]) > 7 else o["date"],
         "value": float(o["value"])}
        for o in obs
        if o["value"] not in (".", "") and not math.isnan(float(o["value"] if o["value"] not in (".", "") else "nan") if o["value"] not in (".", "") else 0)
    ]


def build_claims():
    # IC4WSA: weekly, keep last 104 weeks — use full date (not month-truncated)
    url = (
        f"https://api.stlouisfed.org/fred/series/observations"
        f"?series_id=IC4WSA&api_key={FRED_API_KEY}&file_type=json"
        f"&sort_order=desc&limit=104"
    )
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; MarketPhase/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = json.loads(resp.read())

    data = [
        {"date": o["date"], "value": float(o["value"])}
        for o in body.get("observations", [])
        if o["value"] not in (".", "")
    ]
    data.reverse()  # oldest first

    if len(data) < 5:
        raise ValueError("Insufficient claims data from FRED")

    latest       = data[-1]["value"]
    previous     = data[-2]["value"]
    four_ago     = data[-5]["value"]
    is_improving = latest < four_ago

    return {
        "data": data,
        "latest": latest,
        "previous": previous,
        "fourWeeksAgo": four_ago,
        "trend": "Improving" if is_improving else "Worsening",
        "trendColor": "green" if is_improving else "red",
        "floorStatus": (
            "Claims Decelerating — Floor Support ✅"
            if is_improving else
            "Claims Rising — Macro Risk ⚠"
        ),
        "fetchedAt": datetime.utcnow().isoformat() + "Z",
    }


def analyse_cfnai(ma3_series, raw_series):
    if not ma3_series:
        return None
    latest = ma3_series[-1]
    v = latest["value"]
    if v > 0.20:
        signal, color, bullish = "Strong Expansion ↑", "green", True
    elif v > 0:
        signal, color, bullish = "Expanding ↑", "green", True
    elif v > -0.70:
        signal, color, bullish = "Below Trend ↓", "amber", False
    else:
        signal, color, bullish = "Recession Risk ↓", "red", False
    return {
        "ma3Series":     ma3_series,
        "rawSeries":     raw_series or [],
        "ma3Latest":     v,
        "ma3LatestDate": latest["date"],
        "rawLatest":     raw_series[-1]["value"] if raw_series else None,
        "rawLatestDate": raw_series[-1]["date"]  if raw_series else None,
        "signal":  signal,
        "color":   color,
        "isBullish": bullish,
        "scored":    bullish,
        "source":    "FRED (CFNAI)",
        "fetchedAt": datetime.utcnow().isoformat() + "Z",
    }


def build_cfnai():
    ma3_series = fred_fetch("CFNAIMA3")
    raw_series = fred_fetch("CFNAI")
    result = analyse_cfnai(ma3_series, raw_series)
    if not result:
        raise ValueError("No CFNAI data from FRED")
    return result


def main():
    errors = []

    print("Fetching IC4WSA (claims)…")
    try:
        claims = build_claims()
        path = OUT_DIR / "claims.json"
        path.write_text(json.dumps(claims, separators=(",", ":")))
        print(f"  ✅ {len(claims['data'])} weeks → {path}")
    except Exception as e:
        print(f"  ❌ Claims failed: {e}", file=sys.stderr)
        errors.append(str(e))

    print("Fetching CFNAI…")
    try:
        cfnai = build_cfnai()
        path = OUT_DIR / "cfnai.json"
        path.write_text(json.dumps(cfnai, separators=(",", ":")))
        print(f"  ✅ CFNAI {cfnai['ma3LatestDate']} = {cfnai['ma3Latest']:.3f} ({cfnai['signal']}) → {path}")
    except Exception as e:
        print(f"  ❌ CFNAI failed: {e}", file=sys.stderr)
        errors.append(str(e))

    if errors:
        print(f"\n{len(errors)} error(s) — FRED data may be stale.", file=sys.stderr)
        sys.exit(1)
    print("\nDone.")


if __name__ == "__main__":
    main()
