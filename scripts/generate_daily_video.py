#!/usr/bin/env python3
"""
Daily Market Video Generator
1. Reads today's digest to get the top story/theme
2. Calls Claude to write an Andrei Jikh-style 10-min script
3. Strips cues → sends clean narration to ElevenLabs (British male voice)
4. Creates slide images with Pillow
5. Combines slides + audio into MP4 with ffmpeg
6. Uploads to YouTube via OAuth2
"""

import os, sys, re, json, time, subprocess, textwrap, shutil
from datetime import date
from pathlib import Path
import urllib.request, urllib.parse, urllib.error

# ── Config ───────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY      = os.environ.get("ANTHROPIC_API_KEY", "")
ELEVENLABS_API_KEY     = os.environ.get("ELEVENLABS_API_KEY", "")
YOUTUBE_CLIENT_ID      = os.environ.get("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET  = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
YOUTUBE_REFRESH_TOKEN  = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")

REPO_ROOT  = Path(__file__).parent.parent
DAILY_DIR  = REPO_ROOT / "finance-hub" / "daily"
TMP_DIR    = Path("/tmp/marketphase_video")

# ElevenLabs — "Daniel" British male voice
ELEVENLABS_VOICE_ID = "onwK4e9ZLuTAKqWW03F9"

SLIDE_W, SLIDE_H = 1920, 1080
FPS = 24


# ── Helpers ───────────────────────────────────────────────────────────────────

def install(pkg):
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "--break-system-packages", "-q"])


def ensure_deps():
    try:
        import PIL
    except ImportError:
        install("Pillow")
    try:
        import google.oauth2.credentials
    except ImportError:
        install("google-auth")
        install("google-auth-oauthlib")
        install("google-api-python-client")


def read_today_digest() -> str:
    today = date.today().isoformat()
    digest_file = DAILY_DIR / f"{today}.html"
    if not digest_file.exists():
        # Try yesterday's if morning run happens before digest
        from datetime import timedelta
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        digest_file = DAILY_DIR / f"{yesterday}.html"
    if not digest_file.exists():
        return "Global markets face uncertainty as inflation pressures persist and central banks signal caution."
    html = digest_file.read_text(encoding="utf-8")
    # Extract text from summary-box and story-card sections
    texts = re.findall(r'class="(?:summary-box|story-card)[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
    clean = " ".join(re.sub(r"<[^>]+>", "", t).strip() for t in texts)
    return clean[:2000] if clean else "Markets are navigating turbulent macro conditions."


def call_claude_script(digest_summary: str, today_display: str) -> str:
    """Generate the full Andrei Jikh-style YouTube script."""
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set")

    prompt = f"""You are a YouTube scriptwriter for a financial channel in the style of Andrei Jikh.
Today is {today_display}. Here is today's market summary to base the video on:

{digest_summary}

Write a compelling ~10-minute YouTube script following ALL of these rules EXACTLY:

TONE: Urgent, highly educational, cinematic, slightly cynical about the Federal Reserve, fiat currency, and government spending. Speak as if decoding a massive geopolitical financial secret mainstream media ignores. Calm but dramatic delivery.

PACING: Short, punchy, conversational sentences. No massive text blocks. Write how a person speaks when explaining a complex mystery.

HOOK (0:00-1:00): Start with a massive, high-stakes claim. Do NOT say "Welcome back to the channel" until after the hook grabs them.

VISUAL/AUDIO CUES: Include bracketed cues throughout like:
[Visual: Dramatic zoom-in on stock chart]
[B-Roll: Jerome Powell testifying, slow motion]
[Sound effect: Record scratch]
[Graphic: National debt counter spinning, glowing red]
[Music: Tension builds]

HUMOR: Include deadpan sarcastic humor. Use "magic" or "illusion" metaphors for fiat currency. Joke about the money printer going "brrr". Make fun of politicians redefining words to hide bad data.

ELI5 ANALOGY: Take one complex concept from today's news and explain it with a dead-simple everyday analogy (coffee shop, Monopoly, casino, etc.)

SPONSOR PIVOT (~2:00 mark): Seamlessly weave the macro crisis into a 30-second sponsor pitch for a crypto/investment platform framed as "protect yourself." Use [SPONSOR] as placeholder. Then jump straight back into the data.

OUTRO: Slightly optimistic but cautious. End with fast-talking disclaimer: "None of this is financial advice, it is purely for entertainment purposes, always do your own research, consult a financial advisor, past performance is not indicative of future results, I am not responsible for any financial decisions you make based on this video, please invest responsibly..."

Target length: ~1500 words (10 minutes at 150 words/minute).

Write the complete script now. Include ALL bracketed cues — they are essential."""

    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 4000,
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
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())
    return result["content"][0]["text"].strip()


def strip_cues(script: str) -> str:
    """Remove bracketed visual/audio cues for TTS narration."""
    clean = re.sub(r'\[.*?\]', '', script)
    clean = re.sub(r'\n{3,}', '\n\n', clean)
    return clean.strip()


def extract_title_and_hook(script: str) -> tuple[str, str]:
    """Pull a YouTube title and short description from the script."""
    lines = [l.strip() for l in script.split('\n') if l.strip()]
    # First non-cue line after removing brackets is usually the hook
    hook_lines = []
    for line in lines[:10]:
        clean = re.sub(r'\[.*?\]', '', line).strip()
        if clean and len(clean) > 20:
            hook_lines.append(clean)
        if len(hook_lines) >= 2:
            break
    hook = " ".join(hook_lines)[:300]
    # Build a dramatic title
    today = date.today().strftime("%B %d, %Y")
    title = f"They're Not Telling You This — Market Crisis Update {today}"
    return title, hook


def tts_elevenlabs(text: str, out_path: Path) -> Path:
    """Convert text to speech via ElevenLabs API."""
    if not ELEVENLABS_API_KEY:
        raise ValueError("ELEVENLABS_API_KEY not set")

    # ElevenLabs has ~10k char limit on free tier; chunk if needed
    MAX_CHARS = 4500
    chunks = []
    while text:
        if len(text) <= MAX_CHARS:
            chunks.append(text)
            break
        # Find last sentence boundary before limit
        split_at = text.rfind('. ', 0, MAX_CHARS)
        if split_at == -1:
            split_at = MAX_CHARS
        chunks.append(text[:split_at + 1])
        text = text[split_at + 1:].strip()

    audio_parts = []
    for i, chunk in enumerate(chunks):
        chunk_path = out_path.parent / f"audio_chunk_{i}.mp3"
        payload = json.dumps({
            "text": chunk,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }).encode()
        req = urllib.request.Request(
            f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
            data=payload,
            headers={
                "xi-api-key": ELEVENLABS_API_KEY,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            chunk_path.write_bytes(resp.read())
        audio_parts.append(str(chunk_path))
        print(f"  Audio chunk {i+1}/{len(chunks)} done", file=sys.stderr)
        time.sleep(1)

    if len(audio_parts) == 1:
        shutil.copy(audio_parts[0], out_path)
    else:
        # Concatenate with ffmpeg
        list_file = out_path.parent / "concat_list.txt"
        list_file.write_text("\n".join(f"file '{p}'" for p in audio_parts))
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(list_file), "-c", "copy", str(out_path)
        ], check=True, capture_output=True)

    return out_path


def get_audio_duration(audio_path: Path) -> float:
    """Get audio duration in seconds using ffprobe."""
    result = subprocess.run([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", str(audio_path)
    ], capture_output=True, text=True)
    info = json.loads(result.stdout)
    return float(info["format"]["duration"])


def create_slides(script: str, tmp_dir: Path) -> list[tuple[Path, float]]:
    """
    Create slide images from the script.
    Returns list of (image_path, duration_seconds) tuples.
    """
    from PIL import Image, ImageDraw, ImageFont

    # Parse script into sections
    sections = []
    current_section = []
    for line in script.split('\n'):
        line = line.strip()
        if not line:
            if current_section:
                sections.append('\n'.join(current_section))
                current_section = []
        else:
            current_section.append(line)
    if current_section:
        sections.append('\n'.join(current_section))

    # Group into ~8 slides
    num_slides = min(8, max(4, len(sections)))
    chunk_size = max(1, len(sections) // num_slides)
    slide_texts = []
    for i in range(0, len(sections), chunk_size):
        group = sections[i:i + chunk_size]
        text = '\n\n'.join(group)
        # Remove cues and trim
        text = re.sub(r'\[.*?\]', '', text).strip()
        if text:
            slide_texts.append(text[:400])

    # Colors
    BG_COLOR = (10, 15, 30)
    ACCENT   = (29, 78, 216)
    TEXT     = (248, 250, 252)
    MUTED    = (100, 116, 139)
    RED      = (220, 38, 38)

    # Try to load a font, fall back to default
    def get_font(size, bold=False):
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
        for fp in font_paths:
            if Path(fp).exists():
                return ImageFont.truetype(fp, size)
        return ImageFont.load_default()

    slide_paths = []
    today_str = date.today().strftime("%B %d, %Y")

    for idx, text in enumerate(slide_texts):
        img = Image.new("RGB", (SLIDE_W, SLIDE_H), BG_COLOR)
        draw = ImageDraw.Draw(img)

        # Gradient-like top bar
        for y in range(6):
            alpha = int(255 * (1 - y / 6))
            draw.rectangle([(0, y), (SLIDE_W, y + 1)], fill=ACCENT)

        # MarketPhase watermark top-left
        brand_font = get_font(28, bold=True)
        draw.text((60, 30), "MARKETPHASE", font=brand_font, fill=ACCENT)

        # Date top-right
        date_font = get_font(24)
        draw.text((SLIDE_W - 300, 35), today_str, font=date_font, fill=MUTED)

        # Slide number
        num_font = get_font(20)
        draw.text((60, SLIDE_H - 50), f"{idx + 1} / {len(slide_texts)}", font=num_font, fill=MUTED)

        # Main text — wrap and render
        body_font = get_font(42, bold=(idx == 0))
        margin = 100
        max_w = SLIDE_W - margin * 2
        wrapped = textwrap.fill(text, width=55)
        lines = wrapped.split('\n')

        total_h = len(lines) * 56
        y_start = (SLIDE_H - total_h) // 2

        for li, line in enumerate(lines):
            color = TEXT if li > 0 else (255, 255, 255)
            if idx == 0 and li == 0:
                color = (255, 200, 50)  # Golden hook line
            draw.text((margin, y_start + li * 56), line, font=body_font, fill=color)

        # Bottom red accent bar for dramatic effect
        draw.rectangle([(0, SLIDE_H - 4), (SLIDE_W, SLIDE_H)], fill=RED)

        out = tmp_dir / f"slide_{idx:03d}.png"
        img.save(out, "PNG")
        slide_paths.append(out)

    return slide_paths


def build_video(slide_paths: list[Path], audio_path: Path, out_path: Path):
    """Combine slides + audio into MP4 using ffmpeg."""
    if not shutil.which("ffmpeg"):
        print("Installing ffmpeg…", file=sys.stderr)
        subprocess.run(["apt-get", "install", "-y", "-q", "ffmpeg"], check=True)

    audio_duration = get_audio_duration(audio_path)
    num_slides = len(slide_paths)
    secs_per_slide = audio_duration / num_slides

    # Write concat list with durations
    concat_file = out_path.parent / "slides_concat.txt"
    with concat_file.open("w") as f:
        for slide in slide_paths:
            f.write(f"file '{slide.resolve()}'\n")
            f.write(f"duration {secs_per_slide:.3f}\n")
        # ffmpeg concat needs last file repeated without duration
        f.write(f"file '{slide_paths[-1].resolve()}'\n")

    print(f"  Building video ({audio_duration:.0f}s, {num_slides} slides)…", file=sys.stderr)
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-i", str(audio_path),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        str(out_path)
    ], check=True, capture_output=True)
    print(f"  Video saved: {out_path}", file=sys.stderr)


def get_youtube_access_token() -> str:
    """Exchange refresh token for access token."""
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
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    return result["access_token"]


def upload_to_youtube(video_path: Path, title: str, description: str) -> str:
    """Upload video to YouTube. Returns video URL."""
    access_token = get_youtube_access_token()
    today_str = date.today().isoformat()

    metadata = json.dumps({
        "snippet": {
            "title": title[:100],
            "description": description + f"\n\n#markets #finance #investing #stocks #economy\n\nPublished: {today_str}",
            "tags": ["markets", "finance", "investing", "stocks", "economy", "MarketPhase", "market update"],
            "categoryId": "25",  # News & Politics
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        }
    }).encode()

    # Multipart upload
    boundary = "==boundary=="
    video_bytes = video_path.read_bytes()

    body = (
        f"--{boundary}\r\n"
        f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
    ).encode() + metadata + (
        f"\r\n--{boundary}\r\n"
        f"Content-Type: video/mp4\r\n\r\n"
    ).encode() + video_bytes + f"\r\n--{boundary}--".encode()

    req = urllib.request.Request(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=multipart&part=snippet,status",
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
    return url


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    today = date.today()
    today_display = today.strftime("%A, %B %-d, %Y")
    print(f"=== Daily Video Generator — {today_display} ===", file=sys.stderr)

    ensure_deps()
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Read today's digest
    print("Reading digest…", file=sys.stderr)
    digest_summary = read_today_digest()

    # 2. Generate script with Claude
    print("Generating script with Claude…", file=sys.stderr)
    script = call_claude_script(digest_summary, today_display)
    script_path = TMP_DIR / "script.txt"
    script_path.write_text(script, encoding="utf-8")
    print(f"  Script: {len(script.split())} words", file=sys.stderr)

    # 3. Strip cues for TTS
    narration = strip_cues(script)

    # 4. ElevenLabs TTS
    print("Generating voiceover with ElevenLabs…", file=sys.stderr)
    audio_path = TMP_DIR / "narration.mp3"
    tts_elevenlabs(narration, audio_path)

    # 5. Create slides
    print("Creating slides…", file=sys.stderr)
    slide_paths = create_slides(script, TMP_DIR)
    print(f"  {len(slide_paths)} slides created", file=sys.stderr)

    # 6. Build MP4
    print("Building video…", file=sys.stderr)
    video_path = TMP_DIR / f"marketphase_{today.isoformat()}.mp4"
    build_video(slide_paths, audio_path, video_path)

    # 7. Upload to YouTube
    print("Uploading to YouTube…", file=sys.stderr)
    title, description = extract_title_and_hook(script)
    url = upload_to_youtube(video_path, title, description)
    print(f"\nDone! Watch at: {url}", file=sys.stderr)


if __name__ == "__main__":
    main()
