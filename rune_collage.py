"""Build a single lightweight triptych for three-rune spreads."""

from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageOps


CARD_HEIGHT = 720
GAP = 14
PADDING = 18
BACKGROUNDS = {
    "light": (242, 225, 199),
    "dark": (25, 22, 30),
    "premium": (207, 199, 226),
}


def build_spread_collage(image_paths: list[str], palette: str) -> str:
    """Return a cached /tmp JPEG containing the three cards side by side."""
    if len(image_paths) != 3:
        raise ValueError("A three-rune spread requires exactly three images")

    source_paths = [Path(path) for path in image_paths]
    signature = "|".join(f"{path}:{path.stat().st_mtime_ns}" for path in source_paths)
    digest = hashlib.sha256(f"{palette}|{signature}".encode()).hexdigest()[:20]
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
    canvas_height = CARD_HEIGHT + PADDING * 2
    canvas = Image.new("RGB", (canvas_width, canvas_height), BACKGROUNDS.get(palette, BACKGROUNDS["light"]))

    x = PADDING
    for card in cards:
        canvas.paste(card, (x, PADDING))
        x += card.width + GAP

    canvas.save(output_path, "JPEG", quality=88, optimize=True, progressive=True)
    return str(output_path)
