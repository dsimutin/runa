from pathlib import Path

import bot
import product_runtime_final  # applies final handlers and support request flow

PREMIUM_DIR_CANDIDATES = ["premium", "Premium", "Премиум", "премиум"]
IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp"]


def safer_get_rune_image_path(rune: dict, palette: str) -> str | None:
    image_file = rune.get("image_file") or ""
    rune_key = (rune.get("key") or "").lower().strip()
    wanted = Path(image_file)
    wanted_stem = wanted.stem.lower()
    wanted_number = wanted_stem.split("-", 1)[0] if "-" in wanted_stem else ""
    wanted_name = wanted_stem.split("-", 1)[-1]

    deck_dirs = PREMIUM_DIR_CANDIDATES if palette == "premium" else [bot.DECK_DIRS.get(palette, "light")]
    folders = []
    for deck_dir in deck_dirs:
        folders.append(Path(bot.BASE_DIR) / deck_dir)
        folders.append(Path(bot.BASE_DIR) / "decks" / deck_dir)

    for folder in folders:
        exact = folder / image_file
        if exact.exists():
            return str(exact)

    for folder in folders:
        if not folder.exists() or not folder.is_dir():
            continue
        files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]

        # Case-insensitive exact name.
        for p in files:
            if p.name.lower() == image_file.lower():
                return str(p)

        # Match by rune key/name: berkana, jera, fehu, etc.
        if rune_key:
            for p in files:
                if rune_key in p.stem.lower():
                    return str(p)

        if wanted_name:
            for p in files:
                if wanted_name in p.stem.lower():
                    return str(p)

        # Match by number prefix: 12-jera.jpg can match 12.jpg or 12.png.
        if wanted_number.isdigit():
            for p in files:
                stem = p.stem.lower()
                if stem == wanted_number or stem.startswith(wanted_number + "-") or stem.startswith(wanted_number + "_"):
                    return str(p)

    bot.logger.warning(
        "Rune image not found by safer matcher: palette=%s rune=%s image_file=%s folders=%s",
        palette,
        rune_key,
        image_file,
        folders,
    )
    return None


bot.get_rune_image_path = safer_get_rune_image_path

if __name__ == "__main__":
    bot.main()
