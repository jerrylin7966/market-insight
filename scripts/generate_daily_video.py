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

# ── Config ───────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY      = os.environ.get("ANTHROPIC_API_KEY", "")
ELEVENLABS_API_KEY     = os.environ.get("ELEVENLABS_API_KEY", "")
PEXELS_API_KEY         = os.environ.get("PEXELS_API_KEY", "")
PIXABAY_API_KEY        = os.environ.get("PIXABAY_API_KEY", "")
YOUTUBE_CLIENT_ID      = os.environ.get("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET  = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
YOUTUBE_REFRESH_TOKEN  = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")

REPO_ROOT  = Path(__file__).parent.parent
DAILY_DIR  = REPO_ROOT / "finance-hub" / "daily"
TMP_DIR    = Path("/tmp/marketphase_video")

ELEVENLABS_VOICE_ID = "G17SuINrv2H9FC6nvetn"
SITE_URL = "https://market-phase.com/"

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


# ── Claude: generate script + slide data ─────────────────────────────────────

def call_claude(digest_summary: str, today_display: str) -> dict:
    """Returns dict with 'narration' (full script) and 'slides' (list of slide dicts)."""
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set")

    prompt = f"""You are a YouTube scriptwriter for "Tech Me Home", a financial channel covering MarketPhase daily news.
Today is {today_display}. Today's market summary:

{digest_summary}

Output a JSON object with exactly these two keys:

1. "narration": The full ~10-minute spoken script following ALL these rules:
   - INTRO: Start with a massive high-stakes hook (0:00-1:00). After the hook, say "Welcome back to Tech Me Home, Market Phase daily news!"
   - TONE: Urgent, cinematic, educational. Slightly cynical about the Federal Reserve and fiat currency. Calm but dramatic.
   - SENTENCES: Short, punchy, conversational. Write how a person speaks.
   - CUES: Include [Visual:], [B-Roll:], [Sound effect:], [Graphic:] cues throughout
   - HUMOR: Deadpan sarcasm. "Magic/illusion" metaphors for fiat. Money printer "brrr" jokes.
   - ELI5: Explain one complex concept with a dead-simple analogy (coffee, Monopoly, casino)
   - SPONSOR: At ~2 min weave in a 30-sec [SPONSOR] pitch framed as "protect yourself"
   - OUTRO: Slightly optimistic. End with fast disclaimer: "None of this is financial advice, purely for entertainment, always do your own research..."
   - LENGTH: ~1500 words

2. "slides": Array of 8-10 slide objects. Each slide covers one section of the video. Format:
   {{
     "title": "SHORT SLIDE TITLE IN CAPS",
     "bullets": ["Bullet point 1", "Bullet point 2", "Bullet point 3"],
     "pexels_keyword": "specific search term for background image",
     "narration_text": "The exact spoken words from the narration that play while this slide is shown"
   }}
   Rules for slides:
   - bullets: max 3 per slide, each max 10 words, key facts only — NO full sentences
   - pexels_keyword: be specific and visual (e.g. "federal reserve building", "gold bars vault", "wall street trading floor", "inflation grocery prices", "stock market crash red screen")
   - narration_text: copy the exact portion of the narration script that belongs to this slide — this is used to time the slide duration precisely to the spoken audio
   - First slide: hook/title card
   - Last slide: outro with MarketPhase branding
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
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())

    raw = result["content"][0]["text"].strip()
    # Strip markdown code fences if present
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    return json.loads(raw)


# ── ElevenLabs TTS ────────────────────────────────────────────────────────────

def strip_cues(script: str) -> str:
    clean = re.sub(r'\[.*?\]', '', script)
    clean = re.sub(r'\n{3,}', '\n\n', clean)
    return clean.strip()


def tts_elevenlabs(text: str, out_path: Path) -> Path:
    if not ELEVENLABS_API_KEY:
        raise ValueError("ELEVENLABS_API_KEY not set")

    voice_id = ELEVENLABS_VOICE_ID
    print(f"  Using voice ID: {voice_id}", file=sys.stderr)

    MAX_CHARS = 4500
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

    audio_parts = []
    for i, chunk in enumerate(chunks):
        chunk_path = out_path.parent / f"audio_chunk_{i}.mp3"
        payload = json.dumps({
            "text": chunk,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
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
        with urllib.request.urlopen(req, timeout=60) as resp:
            chunk_path.write_bytes(resp.read())
        audio_parts.append(str(chunk_path))
        print(f"  Audio chunk {i+1}/{len(chunks)} done", file=sys.stderr)
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

    # ── Try Pexels ──
    if PEXELS_API_KEY:
        try:
            query = urllib.parse.quote(keyword)
            req = urllib.request.Request(
                f"https://api.pexels.com/v1/search?query={query}&per_page=8&orientation=landscape",
                headers={
                    "Authorization": PEXELS_API_KEY,
                    "User-Agent": "MarketPhase/1.0 (https://market-phase.com)",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            photos = data.get("photos", [])
            if photos:
                photo = random.choice(photos)
                img_url = photo["src"]["large2x"]
                print(f"  [Pexels] '{keyword}'", file=sys.stderr)
                urllib.request.urlretrieve(img_url, str(img_path))
                return img_path
        except Exception as e:
            print(f"  Pexels failed ('{keyword}'): {e}", file=sys.stderr)

    # ── Fall back to Pixabay ──
    if PIXABAY_API_KEY:
        try:
            query = urllib.parse.quote(keyword)
            req = urllib.request.Request(
                f"https://pixabay.com/api/?key={PIXABAY_API_KEY}"
                f"&q={query}&image_type=photo&orientation=horizontal"
                f"&per_page=8&safesearch=true&min_width=1280",
                headers={"User-Agent": "MarketPhase/1.0"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            hits = data.get("hits", [])
            if hits:
                hit = random.choice(hits)
                img_url = hit.get("largeImageURL") or hit.get("webformatURL")
                print(f"  [Pixabay] '{keyword}'", file=sys.stderr)
                urllib.request.urlretrieve(img_url, str(img_path))
                return img_path
        except Exception as e:
            print(f"  Pixabay failed ('{keyword}'): {e}", file=sys.stderr)

    return None


# ── Slide rendering ───────────────────────────────────────────────────────────

def get_font(size, bold=False):
    from PIL import ImageFont
    paths_bold = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
    ]
    paths_reg = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
    ]
    for fp in (paths_bold if bold else paths_reg):
        if Path(fp).exists():
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


def create_slides(slides_data: list[dict], tmp_dir: Path) -> list[Path]:
    from PIL import Image, ImageDraw, ImageFilter

    ACCENT  = (29, 78, 216)    # blue
    WHITE   = (255, 255, 255)
    YELLOW  = (251, 191, 36)
    MUTED   = (148, 163, 184)
    RED     = (239, 68, 68)
    BG_DARK = (10, 15, 30)

    slide_paths = []
    today_str = date.today().strftime("%B %d, %Y")

    for idx, slide in enumerate(slides_data):
        title   = slide.get("title", "MARKET UPDATE")
        bullets = slide.get("bullets", [])
        keyword = slide.get("pexels_keyword", "finance stock market")
        is_first = idx == 0
        is_last  = idx == len(slides_data) - 1

        # ── Background ──
        bg_path = fetch_pexels_image(keyword, idx, tmp_dir)
        if bg_path and bg_path.exists():
            img = Image.open(bg_path).convert("RGB")
            img = img.resize((SLIDE_W, SLIDE_H), Image.LANCZOS)
            # Slight blur so text pops
            img = img.filter(ImageFilter.GaussianBlur(radius=2))
        else:
            img = Image.new("RGB", (SLIDE_W, SLIDE_H), BG_DARK)

        draw = ImageDraw.Draw(img)

        # ── Dark gradient overlay (bottom 70% of image) ──
        overlay = Image.new("RGBA", (SLIDE_W, SLIDE_H), (0, 0, 0, 0))
        ov_draw = ImageDraw.Draw(overlay)
        gradient_top = int(SLIDE_H * 0.2)
        for y in range(gradient_top, SLIDE_H):
            alpha = int(200 * (y - gradient_top) / (SLIDE_H - gradient_top))
            ov_draw.rectangle([(0, y), (SLIDE_W, y + 1)], fill=(5, 10, 20, alpha))
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(img)

        # ── Top bar ──
        draw.rectangle([(0, 0), (SLIDE_W, 6)], fill=ACCENT)

        # ── MarketPhase logo top-left ──
        brand_font = get_font(30, bold=True)
        draw.text((50, 28), "MARKETPHASE", font=brand_font, fill=WHITE)
        draw.text((50, 28), "MARKET", font=brand_font, fill=WHITE)
        # "PHASE" in blue accent colour
        mw = draw.textlength("MARKET", font=brand_font)
        draw.text((50 + mw, 28), "PHASE", font=brand_font, fill=(96, 165, 250))

        # ── Channel name top-right ──
        ch_font = get_font(22)
        draw.text((SLIDE_W - 350, 32), "Tech Me Home", font=ch_font, fill=MUTED)

        # ── Date bottom-right ──
        date_font = get_font(22)
        draw.text((SLIDE_W - 280, SLIDE_H - 50), today_str, font=date_font, fill=MUTED)

        # ── Slide number bottom-left ──
        num_font = get_font(20)
        draw.text((50, SLIDE_H - 50), f"{idx + 1} / {len(slides_data)}",
                  font=num_font, fill=MUTED)

        # ── Bottom accent bar ──
        draw.rectangle([(0, SLIDE_H - 5), (SLIDE_W, SLIDE_H)], fill=RED)

        # ── Title ──
        title_font = get_font(72 if not is_first else 90, bold=True)
        title_color = YELLOW if is_first else WHITE
        # Word-wrap title
        title_wrapped = textwrap.fill(title, width=30)
        title_lines = title_wrapped.split('\n')
        title_h = len(title_lines) * 82
        title_y = SLIDE_H // 2 - title_h // 2 - (80 if bullets else 0)

        for li, line in enumerate(title_lines):
            draw.text((80, title_y + li * 82), line, font=title_font, fill=title_color)

        # ── Bullet points ──
        if bullets:
            bullet_font = get_font(46)
            bullet_y = title_y + title_h + 40
            for bi, bullet in enumerate(bullets[:3]):
                # Bullet dot
                dot_x = 80
                dot_y = bullet_y + bi * 65 + 20
                draw.ellipse([(dot_x, dot_y), (dot_x + 14, dot_y + 14)], fill=YELLOW)
                # Bullet text
                draw.text((dot_x + 30, bullet_y + bi * 65), bullet,
                          font=bullet_font, fill=WHITE)

        # ── Last slide: add site URL ──
        if is_last:
            url_font = get_font(36, bold=True)
            draw.text((80, SLIDE_H - 130), f"Learn more: {SITE_URL}",
                      font=url_font, fill=(96, 165, 250))

        out = tmp_dir / f"slide_{idx:03d}.png"
        img.save(out, "PNG")
        slide_paths.append(out)
        print(f"  Slide {idx+1}/{len(slides_data)}: {title}", file=sys.stderr)

    return slide_paths


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


def build_video(slide_paths: list[Path], audio_path: Path, out_path: Path,
                slides_data: list[dict] = None):
    audio_duration = get_audio_duration(audio_path)
    num_slides = len(slide_paths)

    if slides_data:
        durations = calc_slide_durations(slides_data, audio_duration)
    else:
        durations = [audio_duration / num_slides] * num_slides

    concat_file = out_path.parent / "slides_concat.txt"
    with concat_file.open("w") as f:
        for slide, dur in zip(slide_paths, durations):
            f.write(f"file '{slide.resolve()}'\n")
            f.write(f"duration {dur:.3f}\n")
        f.write(f"file '{slide_paths[-1].resolve()}'\n")

    avg = audio_duration / num_slides
    print(f"  Building video ({audio_duration:.0f}s, {num_slides} slides, "
          f"~{avg:.1f}s avg/slide)…", file=sys.stderr)
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
    with urllib.request.urlopen(req, timeout=30) as resp:
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


def generate_thumbnail(title: str, pexels_keyword: str, tmp_dir: Path) -> Path:
    """
    Composite thumbnail:
    - Full Pexels image as background
    - Host photo (green screen removed) on the LEFT
    - Bold title text on the RIGHT
    - MarketPhase branding bottom-left
    """
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter, ImageEnhance

    TW, TH = 1280, 720  # YouTube recommended thumbnail size
    YELLOW = (251, 191, 36)
    WHITE  = (255, 255, 255)
    BLACK  = (0, 0, 0)
    RED    = (239, 68, 68)
    ACCENT = (29, 78, 216)

    # ── Background: fetch relevant Pexels image ──
    bg_path = fetch_pexels_image(pexels_keyword, 99, tmp_dir)
    if bg_path and bg_path.exists():
        bg = Image.open(bg_path).convert("RGB").resize((TW, TH), Image.LANCZOS)
        # Slightly darken overall
        bg = ImageEnhance.Brightness(bg).enhance(0.55)
    else:
        bg = Image.new("RGB", (TW, TH), (10, 15, 30))

    bg = bg.convert("RGBA")

    # ── Dark gradient on right half for text readability ──
    grad = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    split = TW // 2
    for x in range(split, TW):
        alpha = int(180 * (x - split) / (TW - split))
        gd.rectangle([(x, 0), (x + 1, TH)], fill=(5, 10, 20, alpha))
    bg = Image.alpha_composite(bg, grad)

    # ── Host photo (random pick, green screen removed) ──
    assets_dir = Path(__file__).parent / "assets"
    host_files = list(assets_dir.glob("host_*.jp*g"))
    if host_files:
        host_path = random.choice(host_files)
        host_img = Image.open(host_path)
        host_img = remove_green_screen(host_img)

        # Scale host to fill ~55% of thumbnail height, keep aspect ratio
        target_h = int(TH * 1.05)  # slightly taller than frame (crop bottom)
        scale = target_h / host_img.height
        target_w = int(host_img.width * scale)
        host_img = host_img.resize((target_w, target_h), Image.LANCZOS)

        # Position: bottom-left, centred in left half
        x_pos = (TW // 2 - target_w) // 2 + 20
        y_pos = TH - target_h + 20  # slight crop at bottom
        bg.paste(host_img, (x_pos, y_pos), host_img)

    # ── Draw title text on the right ──
    draw = ImageDraw.Draw(bg)
    title_font_lg = get_font(68, bold=True)
    title_font_sm = get_font(52, bold=True)

    # Word-wrap to fit right half (~600px wide)
    words = title.split()
    lines, current = [], []
    for word in words:
        test = ' '.join(current + [word])
        if draw.textlength(test, font=title_font_sm) < 540:
            current.append(word)
        else:
            if current:
                lines.append(' '.join(current))
            current = [word]
    if current:
        lines.append(' '.join(current))

    # Stack lines, vertically centred on right half
    line_h = 64
    total_h = len(lines) * line_h
    y_start = (TH - total_h) // 2 - 20
    x_text = TW // 2 + 30

    for i, line in enumerate(lines):
        y = y_start + i * line_h
        # Drop shadow
        draw.text((x_text + 3, y + 3), line, font=title_font_sm, fill=(0, 0, 0, 180))
        # Main text — first line yellow, rest white
        color = YELLOW if i == 0 else WHITE
        draw.text((x_text, y), line, font=title_font_sm, fill=color)

    # ── Red accent bar bottom ──
    draw.rectangle([(0, TH - 6), (TW, TH)], fill=RED)

    # ── MarketPhase branding bottom-left ──
    brand_font = get_font(26, bold=True)
    draw.text((22, TH - 44), "MARKET", font=brand_font, fill=WHITE)
    mw = draw.textlength("MARKET", font=brand_font)
    draw.text((22 + mw, TH - 44), "PHASE", font=brand_font, fill=(96, 165, 250))

    # Save as JPEG (YouTube thumbnail requirement)
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
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp.read()
        print(f"  Thumbnail set ✅", file=sys.stderr)
    except Exception as e:
        print(f"  Thumbnail upload failed (non-fatal): {e}", file=sys.stderr)


def upload_to_youtube(video_path: Path, title: str, hook_text: str,
                      thumbnail_path: Path | None = None) -> str:
    access_token = get_youtube_access_token()
    today_str = date.today().strftime("%B %d, %Y")

    description = (
        f"{hook_text}\n\n"
        f"Learn world-wide financial insights: {SITE_URL}\n\n"
        f"Track live market signals, economic indicators, and daily market analysis at MarketPhase.\n\n"
        f"📅 Published: {today_str}\n\n"
        f"#markets #finance #investing #stocks #economy #MarketPhase #TechMeHome\n\n"
        f"⚠️ None of this is financial advice. For entertainment and educational purposes only. "
        f"Always do your own research."
    )

    metadata = json.dumps({
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": ["markets", "finance", "investing", "stocks", "economy",
                     "MarketPhase", "TechMeHome", "market update", "daily news",
                     "financial news", "stock market today"],
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


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    today = date.today()
    today_display = today.strftime("%A, %B %-d, %Y")
    print(f"=== Daily Video Generator — {today_display} ===", file=sys.stderr)

    ensure_deps()
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Read digest
    print("Reading digest…", file=sys.stderr)
    digest_summary = read_today_digest()

    # 2. Generate script + slide data
    print("Generating script + slides with Claude…", file=sys.stderr)
    data = call_claude(digest_summary, today_display)
    narration_script = data["narration"]
    slides_data      = data["slides"]
    print(f"  Script: {len(narration_script.split())} words, "
          f"{len(slides_data)} slides", file=sys.stderr)

    # 3. TTS narration (strip visual cues first)
    print("Generating voiceover with ElevenLabs…", file=sys.stderr)
    narration_clean = strip_cues(narration_script)
    audio_path = TMP_DIR / "narration.mp3"
    tts_elevenlabs(narration_clean, audio_path)

    # 4. Create slides with Pexels backgrounds
    print("Creating slides…", file=sys.stderr)
    slide_paths = create_slides(slides_data, TMP_DIR)

    # 5. Build MP4
    print("Building video…", file=sys.stderr)
    video_path = TMP_DIR / f"marketphase_{today.isoformat()}.mp4"
    build_video(slide_paths, audio_path, video_path, slides_data)

    # 6. Generate thumbnail (host photo + Pexels bg + title text)
    print("Generating thumbnail…", file=sys.stderr)
    title = f"They're Not Telling You This | Market Update {today.strftime('%b %d, %Y')}"
    thumb_keyword = slides_data[0].get("pexels_keyword", "stock market finance") if slides_data else "stock market"
    thumbnail_path = generate_thumbnail(title, thumb_keyword, TMP_DIR)

    # 7. Upload to YouTube
    print("Uploading to YouTube…", file=sys.stderr)
    hook_lines = [l.strip() for l in narration_script.split('\n')
                  if l.strip() and not l.strip().startswith('[')][:3]
    hook_text = " ".join(hook_lines)[:300]
    url = upload_to_youtube(video_path, title, hook_text, thumbnail_path)

    print(f"\n✅ Done! Watch at: {url}", file=sys.stderr)


if __name__ == "__main__":
    main()
