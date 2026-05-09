#!/usr/bin/env python3
"""
One-time Seedance clip library generator for MarketPhase daily videos.

Generates 20 cinematic finance background clips and saves them to
scripts/assets/clips/{tag}.mp4

Run once locally:
  pip install requests
  python scripts/generate_clip_library.py

Skips any clip that already exists, so safe to re-run if interrupted.
Cost: 25 credits per 5-sec clip × 20 clips = 500 credits total (~$49)
"""

import os
import sys
import time
import requests
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
API_KEY   = os.environ.get("SEEDANCE_API_KEY", "sk-sd_0bWwtYs8ceFCd3tHktS7WM7ptaYpLIdPcxd8m0wt")
BASE_URL  = "https://seedance2.app/api/v1"
CLIPS_DIR = Path(__file__).parent / "assets" / "clips"

HEADERS = {"Authorization": f"Bearer {API_KEY}"}

# ── Clip library ──────────────────────────────────────────────────────────────
# Each entry: tag (used for keyword matching) + cinematic prompt
# All prompts are designed as slow-moving backgrounds — subtle motion,
# dark enough that white text overlays remain readable.
CLIPS = [
    {
        "tag": "stock_bull",
        "prompt": (
            "Cinematic slow zoom into a stock market ticker board with rising green numbers, "
            "dramatic warm trading floor lighting, shallow depth of field, 4K quality, no text"
        ),
    },
    {
        "tag": "stock_crash",
        "prompt": (
            "Cinematic close-up of red declining stock charts on multiple screens in a dark "
            "trading room, dramatic deep red ambient light, slow dolly, no text"
        ),
    },
    {
        "tag": "federal_reserve",
        "prompt": (
            "Cinematic slow pan across the Federal Reserve building exterior, overcast dramatic "
            "sky, neoclassical stone columns, desaturated cool grade, no text"
        ),
    },
    {
        "tag": "wall_street",
        "prompt": (
            "Cinematic overhead slow pan of a busy trading floor with traders at terminals, "
            "dramatic overhead lighting, warm tones, shallow depth of field, no text"
        ),
    },
    {
        "tag": "inflation",
        "prompt": (
            "Cinematic slow dolly through supermarket aisles, price tags in soft focus, "
            "warm slightly overexposed lighting, shallow depth of field, no text"
        ),
    },
    {
        "tag": "gold",
        "prompt": (
            "Cinematic slow dolly along stacked gold bars in a dark vault, warm dramatic golden "
            "side lighting, deep shadows, shallow depth of field, no text"
        ),
    },
    {
        "tag": "crypto",
        "prompt": (
            "Abstract cinematic visualization of a glowing cryptocurrency network, blue and "
            "purple nodes slowly connecting in dark space, slow drift, no text"
        ),
    },
    {
        "tag": "oil_energy",
        "prompt": (
            "Cinematic slow aerial push toward an oil refinery at dusk, industrial silhouettes, "
            "deep orange and amber sky, dramatic atmosphere, no text"
        ),
    },
    {
        "tag": "recession",
        "prompt": (
            "Cinematic empty city street at dawn, closed shop fronts, desaturated cool blue "
            "grade, slow dolly forward, moody overcast light, no text"
        ),
    },
    {
        "tag": "interest_rates",
        "prompt": (
            "Cinematic close-up of a rising yield curve graph glowing on a dark monitor, "
            "single cool blue light source, slow zoom in, dark room, no text"
        ),
    },
    {
        "tag": "global_economy",
        "prompt": (
            "Cinematic slow rotation of Earth globe with glowing trade route lines connecting "
            "major cities, dark space background, deep blue and white tones, no text"
        ),
    },
    {
        "tag": "tech_stocks",
        "prompt": (
            "Cinematic macro shot of semiconductor chips and circuit boards under dramatic "
            "directional side lighting, slow focus pull, cool blue and silver tones, no text"
        ),
    },
    {
        "tag": "jobs",
        "prompt": (
            "Cinematic golden hour morning light streaming into a modern open-plan office, "
            "workers at desks with monitors, slow pan right, warm soft tones, no text"
        ),
    },
    {
        "tag": "bonds",
        "prompt": (
            "Cinematic close-up of a financial terminal showing bond yield curves, green "
            "monochrome data on dark screen, slow zoom out, dark surrounding, no text"
        ),
    },
    {
        "tag": "consumer",
        "prompt": (
            "Cinematic slow motion close-up of a contactless credit card payment, warm retail "
            "lighting, shallow depth of field, bokeh background, no text"
        ),
    },
    {
        "tag": "earnings",
        "prompt": (
            "Cinematic laptop screen showing rising financial bar charts, coffee cup beside it, "
            "soft morning window light, slow gentle zoom in, shallow depth of field, no text"
        ),
    },
    {
        "tag": "nyse_open",
        "prompt": (
            "Cinematic wide shot of the New York Stock Exchange facade at sunrise, "
            "American flags, dramatic golden sky, slow upward tilt, no text"
        ),
    },
    {
        "tag": "dollar",
        "prompt": (
            "Cinematic macro slow motion of US dollar bills fanning out, dramatic directional "
            "side lighting, dark background, shallow depth of field, no text"
        ),
    },
    {
        "tag": "bear_market",
        "prompt": (
            "Cinematic dark abstract visualization of falling red market lines dissolving "
            "downward, brooding storm atmosphere, slow downward camera drift, no text"
        ),
    },
    {
        "tag": "data_screens",
        "prompt": (
            "Cinematic wide shot of a dark financial analytics room with multiple blue-lit data "
            "screens showing scrolling numbers and charts, slow zoom out, no text"
        ),
    },
    # ── Branded channel intro (10 sec) ──────────────────────────────────────
    {
        "tag": "channel_intro",
        "duration": 10,
        "prompt": (
            "Cinematic animated title sequence, bold glowing text emerging from darkness, "
            "financial data streams and market charts flowing in the background, deep blue and "
            "gold colour palette, dramatic light rays, epic orchestral energy, "
            "professional broadcast intro feel, no spoken words, no text overlays"
        ),
    },
    # ── Extended topic library (5 sec each) ─────────────────────────────────
    {
        "tag": "housing_market",
        "prompt": (
            "Cinematic slow zoom toward a row of suburban houses at golden hour, "
            "real estate for sale signs in soft focus, warm amber tones, shallow depth of field, no text"
        ),
    },
    {
        "tag": "banking",
        "prompt": (
            "Cinematic slow dolly through a grand bank interior, marble columns, "
            "teller windows, dramatic overhead lighting, cool desaturated grade, no text"
        ),
    },
    {
        "tag": "china_trade",
        "prompt": (
            "Cinematic aerial slow pan over a massive container shipping port at dusk, "
            "cranes and stacked containers, industrial haze, deep blue and orange tones, no text"
        ),
    },
    {
        "tag": "us_debt",
        "prompt": (
            "Cinematic slow zoom into the US Capitol building at night, dramatic uplighting, "
            "dark moody sky, desaturated blue grade, slight haze, no text"
        ),
    },
    {
        "tag": "ai_stocks",
        "prompt": (
            "Cinematic abstract visualization of glowing neural network nodes pulsing and "
            "connecting, deep purple and cyan tones, slow drift, futuristic dark background, no text"
        ),
    },
    {
        "tag": "commodities",
        "prompt": (
            "Cinematic slow aerial push over vast golden wheat fields at sunrise, "
            "warm harvest tones, gentle wind ripple, shallow depth of field, no text"
        ),
    },
    {
        "tag": "retail_earnings",
        "prompt": (
            "Cinematic slow dolly through a large modern retail store interior, "
            "product shelves in soft focus, warm commercial lighting, no customers, no text"
        ),
    },
    {
        "tag": "ipo",
        "prompt": (
            "Cinematic close-up of a stock exchange opening bell ceremony, brass bell, "
            "confetti falling in slow motion, warm celebratory lighting, no text"
        ),
    },
    {
        "tag": "supply_chain",
        "prompt": (
            "Cinematic aerial shot of a cargo ship moving slowly through open ocean at dawn, "
            "mist on the water, dramatic sky, cool blue tones, slow drift, no text"
        ),
    },
    {
        "tag": "mergers",
        "prompt": (
            "Cinematic close-up of two businesspeople's hands shaking across a glass conference "
            "table, city skyline in background bokeh, dramatic side lighting, no text"
        ),
    },
    {
        "tag": "election_market",
        "prompt": (
            "Cinematic slow pan across an empty election night broadcast studio, "
            "multiple screens showing maps, blue and red lighting, dramatic atmosphere, no text"
        ),
    },
    {
        "tag": "healthcare_costs",
        "prompt": (
            "Cinematic close-up of pharmaceutical pills and a stethoscope on a dark surface, "
            "dramatic side lighting, shallow depth of field, cool desaturated grade, no text"
        ),
    },
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def check_credits():
    resp = requests.get(f"{BASE_URL}/credits", headers=HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()["data"]
    print(f"Credits remaining: {data['credits']}")
    return data["credits"]


def start_generation(prompt: str, duration: int = 5) -> str:
    payload = {
        "prompt": prompt,
        "model": "doubao-seedance-1-5-pro",
        "generation_type": "text_to_video",
        "duration": duration,
        "aspect_ratio": "16:9",
        "resolution": "720p",
    }
    resp = requests.post(f"{BASE_URL}/generate", headers=HEADERS,
                         json=payload, timeout=30)
    resp.raise_for_status()
    video_id = resp.json()["data"]["video_id"]
    return video_id


def poll_until_done(video_id: str, tag: str):
    """Poll until completed or failed. Returns video_url or None."""
    print(f"    Polling {video_id} ", end="", flush=True)
    for attempt in range(120):  # max 10 mins
        time.sleep(5)
        resp = requests.get(f"{BASE_URL}/videos/{video_id}",
                            headers=HEADERS, timeout=15)
        result = resp.json()["data"]
        status = result["status"]
        print(".", end="", flush=True)
        if status == "completed":
            print(f" done ({attempt * 5 + 5}s)")
            return result["video_url"]
        elif status == "failed":
            print(f" FAILED: {result.get('error')}")
            return None
    print(" TIMED OUT")
    return None


def download_clip(url: str, dest: Path):
    resp = requests.get(url, stream=True, timeout=60)
    resp.raise_for_status()
    with dest.open("wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("MarketPhase — Seedance Clip Library Generator")
    print("=" * 60)

    credits = check_credits()
    needed  = len(CLIPS) * 25
    existing = [c for c in CLIPS if (CLIPS_DIR / f"{c['tag']}.mp4").exists()]
    to_generate = [c for c in CLIPS if not (CLIPS_DIR / f"{c['tag']}.mp4").exists()]
    credits_needed = sum(c.get("duration", 5) * 5 for c in to_generate)

    print(f"\nTotal clips: {len(CLIPS)}")
    print(f"Already generated: {len(existing)}")
    print(f"To generate: {len(to_generate)} ({credits_needed} credits)")
    if credits < credits_needed:
        print(f"\nWARNING: Only {credits} credits available, need {credits_needed}.")
        print("Will generate as many as possible.")

    if not to_generate:
        print("\nAll clips already exist! Nothing to do.")
        return

    print()
    for i, clip in enumerate(to_generate, 1):
        tag  = clip["tag"]
        dest = CLIPS_DIR / f"{tag}.mp4"
        print(f"[{i}/{len(to_generate)}] {tag}")

        try:
            dur = clip.get("duration", 5)
            video_id = start_generation(clip["prompt"], duration=dur)
            video_url = poll_until_done(video_id, tag)
            if video_url:
                print(f"    Downloading → {dest.name} ...", end=" ", flush=True)
                download_clip(video_url, dest)
                size_kb = dest.stat().st_size // 1024
                print(f"{size_kb} KB ✅")
            else:
                print(f"    Skipping {tag} (generation failed)")
        except Exception as e:
            print(f"    ERROR on {tag}: {e}")

        # Brief pause between jobs to be polite to the API
        if i < len(to_generate):
            time.sleep(2)

    # Summary
    generated = [c for c in CLIPS if (CLIPS_DIR / f"{c['tag']}.mp4").exists()]
    print(f"\n{'=' * 60}")
    print(f"Done! {len(generated)}/{len(CLIPS)} clips in {CLIPS_DIR}")
    remaining = check_credits()
    print(f"Credits used: ~{credits - remaining}  |  Credits remaining: {remaining}")


if __name__ == "__main__":
    main()
