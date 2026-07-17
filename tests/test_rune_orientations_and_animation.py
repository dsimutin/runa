from pathlib import Path

from PIL import Image

from rune_text_repository import (
    is_reversible,
    normalize_orientation,
    orientation_label,
    orientation_symbol,
    random_orientation,
    yes_no_draw,
)
from rune_collage import build_spread_collage
from runes_data import NON_REVERSIBLE_RUNE_KEYS, RUNES
from year_rasklad import build_month_interpretation
from spread_engine_approved import build_unified_spread


def test_non_reversible_runes_never_draw_reversed():
    for rune_key in NON_REVERSIBLE_RUNE_KEYS:
        assert normalize_orientation(rune_key, "rev") == "up"
        assert {random_orientation(rune_key) for _ in range(50)} == {"up"}
        assert orientation_label("rev", rune_key) == "положение не меняется"
        assert orientation_symbol(rune_key, "rev") == "◆"


def test_reversible_runes_keep_both_orientations():
    reversible = {rune["key"] for rune in RUNES if rune["reversible"]}
    assert reversible
    for rune_key in reversible:
        assert is_reversible(rune_key)
        assert normalize_orientation(rune_key, "rev") == "rev"
        assert orientation_symbol(rune_key, "rev") == "↓"


def test_yes_no_for_symmetric_runes_is_not_forced_to_yes():
    outcomes = {yes_no_draw("isa")[1] for _ in range(200)}
    assert outcomes == {"yes", "no"}
    assert {yes_no_draw("isa")[0] for _ in range(20)} == {"up"}


def test_all_three_decks_have_every_card_and_algiz_is_not_othala():
    for palette in ("light", "dark", "premium"):
        for rune in RUNES:
            if rune["key"] == "wyrd":
                filename = rune["palette_image_files"][palette]
            else:
                filename = rune["image_file"]
            assert (Path(palette) / filename).is_file()

    premium_algiz = (Path("premium") / "15-algiz.jpg").read_bytes()
    premium_othala = (Path("premium") / "24-othala.jpg").read_bytes()
    assert premium_algiz != premium_othala


def test_year_spread_uses_month_language_not_daily_card_copy():
    for palette in ("light", "dark", "premium"):
        for rune in RUNES:
            text = build_month_interpretation(rune["key"], palette)
            lowered = text.lower()
            assert "вопрос дня" not in lowered
            assert "сегодня" not in lowered
            assert "тема месяца" in lowered
            assert "ориентир месяца" in lowered


def test_three_card_spread_is_one_horizontal_triptych():
    paths = ["light/01-fehu.jpg", "light/02-uruz.jpg", "light/03-thurisaz.jpg"]
    labels = ["прямое", "перевёрнутое", "положение не меняется"]
    collage_path = build_spread_collage(paths, "light", labels)
    with Image.open(collage_path) as collage:
        assert collage.width > collage.height
        assert collage.height == 820


def test_three_card_text_uses_past_present_and_conditional_future():
    draws = [
        ({"key": "fehu", "name": "Феху"}, "up"),
        ({"key": "uruz", "name": "Уруз"}, "up"),
        ({"key": "thurisaz", "name": "Турисаз"}, "up"),
    ]
    text = build_unified_spread("Что происходит?", draws, "light", "Дмитрий")
    assert "1️⃣ <b>Прошлое — Феху (прямое положение)</b>" in text
    assert "2️⃣ <b>Настоящее — Уруз (прямое положение)</b>" in text
    assert "3️⃣ <b>Будущее — Турисаз (прямое положение)</b>" in text
    assert "Если текущая траектория сохранится:" in text
