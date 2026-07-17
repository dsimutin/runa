"""Build a single lightweight triptych for three-rune spreads."""

from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


CARD_HEIGHT = 720
COLLAGE_VERSION = "2"
GAP = 14
PADDING = 18
BADGE_HEIGHT = 54
BADGE_GAP = 10
BACKGROUNDS = {
    "light": (242, 225, 199),
    "dark": (25, 22, 30),
    "premium": (207, 199, 226),
}
FONT_PATH = Path(__file__).resolve().parent / "assets" / "fonts" / "NotoSans-Regular.ttf"
BADGE_COLOURS = {
    "light": {
        "прямое": (180, 139, 64),
        "перевёрнутое": (137, 91, 112),
        "необратимая": (121, 113, 102),
    },
    "dark": {
        "прямое": (78, 65, 47),
        "перевёрнутое": (82, 49, 78),
        "необратимая": (54, 61, 70),
    },
    "premium": {
        "прямое": (153, 126, 172),
        "перевёрнутое": (99, 68, 126),
        "необратимая": (105, 110, 132),
    },
}
BADGE_OUTLINES = {
    "light": (218, 180, 102),
    "dark": (174, 139, 75),
    "premium": (224, 195, 137),
}


def _badge_text(label: str) -> str:
    if label == "прямое":
        return "ПРЯМАЯ"
    if label == "перевёрнутое":
        return "ПЕРЕВЁРНУТАЯ"
    return "НЕОБРАТИМАЯ"


def build_spread_collage(image_paths: list[str], palette: str, position_labels: list[str]) -> str:
    """Return a cached /tmp JPEG containing the three cards side by side."""
    if len(image_paths) != 3:
        raise ValueError("A three-rune spread requires exactly three images")
    if len(position_labels) != 3:
        raise ValueError("A three-rune spread requires exactly three position labels")

    source_paths = [Path(path) for path in image_paths]
    signature = "|".join(f"{path}:{path.stat().st_mtime_ns}" for path in source_paths)
    font_signature = FONT_PATH.stat().st_mtime_ns
    digest = hashlib.sha256(
        f"{COLLAGE_VERSION}|{palette}|{signature}|{'|'.join(position_labels)}|{font_signature}".encode()
    ).hexdigest()[:20]
    output_path = Path("/tmp") / f"runa-spread-{digest}.jpg"
    if output_path.is_file():
        return str(output_path)

    cards: list[Image.Image] = []
    for path in source_paths:
        with Image.open(path) as source:
            card = ImageOps.exif_transpose(source).convert("RGB")
            width = round(card.width * CARD_HEIGHT / card.height)
            cards.append(card.resize((width, CARD_HEIGHT), Image.Resampling.LANCZOS))

    canvas_width = sum(card.width for card in cards) + GAP * 2 + PADDING * 2
    canvas_height = CARD_HEIGHT + BADGE_HEIGHT + BADGE_GAP + PADDING * 2
    canvas = Image.new("RGB", (canvas_width, canvas_height), BACKGROUNDS.get(palette, BACKGROUNDS["light"]))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(str(FONT_PATH), size=24)

    x = PADDING
    for card, label in zip(cards, position_labels):
        palette_colours = BADGE_COLOURS.get(palette, BADGE_COLOURS["light"])
        colour = palette_colours.get(label, palette_colours["необратимая"])
        draw.rounded_rectangle(
            (x, PADDING, x + card.width, PADDING + BADGE_HEIGHT),
            radius=12,
            fill=colour,
            outline=BADGE_OUTLINES.get(palette, BADGE_OUTLINES["light"]),
            width=2,
        )
        text = _badge_text(label)
        bounds = draw.textbbox((0, 0), text, font=font)
        text_width = bounds[2] - bounds[0]
        text_height = bounds[3] - bounds[1]
        draw.text(
            (x + (card.width - text_width) / 2, PADDING + (BADGE_HEIGHT - text_height) / 2 - bounds[1]),
            text,
            font=font,
            fill=(255, 255, 255),
        )
        canvas.paste(card, (x, PADDING + BADGE_HEIGHT + BADGE_GAP))
        x += card.width + GAP

    canvas.save(output_path, "JPEG", quality=88, optimize=True, progressive=True)
    return str(output_path)
