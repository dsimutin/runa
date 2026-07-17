"""Small, generated-on-demand reveal animations for rune cards.

Animations are intentionally not stored for every card: three decks times 25
cards would make the deploy unnecessarily large.  A compact GIF is rendered on
the first use of a card and cached in the Cloud Run instance memory.  Telegram
then replaces it with the original full-resolution photo after one pass.
"""

from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps


ANIMATION_WIDTH = 360
FRAME_COUNT = 10
FRAME_DURATION_MS = 100
REVEAL_SECONDS = FRAME_COUNT * FRAME_DURATION_MS / 1000


def _diagonal_band(size: tuple[int, int], progress: float, premium: bool) -> Image.Image:
    width, height = size
    # The band travels beyond both edges so the first and last frames are clean.
    center = -0.45 * width + progress * 1.9 * width
    band_width = width * (0.10 if premium else 0.14)
    # Build a one-pixel gradient row and let Pillow's native affine transform
    # extend/slant it.  This is ~20x faster than touching every pixel in Python.
    span = width + height
    values = []
    for x in range(span):
        distance = abs(x - center)
        strength = max(0.0, 1.0 - distance / (band_width * 2.5))
        values.append(int(255 * strength * strength))
    row = Image.new("L", (span, 1), 0)
    row.putdata(values)
    straight = row.resize((span, height))
    return straight.transform(
        size,
        Image.Transform.AFFINE,
        (1, -0.34, 0, 0, 1, 0),
        resample=Image.Resampling.BILINEAR,
    ).filter(ImageFilter.GaussianBlur(radius=max(2, width // 120)))


def _premium_highlight(base: Image.Image, band: Image.Image) -> Image.Image:
    # Restrict most of the shimmer to already luminous/crystalline details.
    luminance = ImageOps.grayscale(base)
    bright = luminance.point(lambda value: max(0, min(255, (value - 105) * 2)))
    crystal_mask = ImageChops.multiply(band, bright)
    glow = Image.new("RGB", base.size, (232, 224, 255))
    frame = Image.composite(glow, base, crystal_mask.point(lambda value: int(value * 0.72)))

    # A restrained champagne point at the centre makes the crystal feel alive.
    width, height = base.size
    sparkle = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(sparkle)
    radius = max(5, width // 42)
    cx, cy = width // 2, int(height * 0.42)
    draw.line((cx - radius * 2, cy, cx + radius * 2, cy), fill=(255, 242, 196, 190), width=1)
    draw.line((cx, cy - radius * 2, cx, cy + radius * 2), fill=(255, 242, 196, 170), width=1)
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=(255, 245, 215, 110))
    sparkle = sparkle.filter(ImageFilter.GaussianBlur(radius=2))
    return Image.alpha_composite(frame.convert("RGBA"), sparkle).convert("RGB")


def _standard_highlight(base: Image.Image, band: Image.Image, palette: str) -> Image.Image:
    colour = (255, 230, 166) if palette == "light" else (224, 204, 255)
    opacity = 0.52 if palette == "light" else 0.38
    glow = Image.new("RGB", base.size, colour)
    return Image.composite(glow, base, band.point(lambda value: int(value * opacity)))


@lru_cache(maxsize=24)
def _render_cached(image_path: str, modified_ns: int, palette: str) -> bytes:
    del modified_ns  # Used as part of the cache key to invalidate changed art.
    with Image.open(image_path) as source:
        source = ImageOps.exif_transpose(source).convert("RGB")
        height = round(source.height * ANIMATION_WIDTH / source.width)
        base = source.resize((ANIMATION_WIDTH, height), Image.Resampling.LANCZOS)

    frames: list[Image.Image] = []
    premium = palette == "premium"
    for index in range(FRAME_COUNT):
        progress = index / (FRAME_COUNT - 1)
        band = _diagonal_band(base.size, progress, premium)
        frame = _premium_highlight(base, band) if premium else _standard_highlight(base, band, palette)
        # Palette mode keeps the Telegram GIF compact without flattening detail.
        frames.append(frame.quantize(colors=128, method=Image.Quantize.MEDIANCUT))

    output = BytesIO()
    frames[0].save(
        output,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=FRAME_DURATION_MS,
        loop=0,
        optimize=True,
        disposal=2,
    )
    return output.getvalue()


def build_reveal_animation(image_path: str, palette: str) -> BytesIO:
    path = Path(image_path)
    data = _render_cached(str(path), path.stat().st_mtime_ns, palette)
    stream = BytesIO(data)
    stream.name = f"{path.stem}-{palette}-reveal.gif"
    return stream
