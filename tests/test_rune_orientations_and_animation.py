from pathlib import Path

from PIL import Image, ImageStat

from rune_text_repository import (
    draw_yes_no_rune,
    get_sphere_answer,
    detect_question_sphere,
    is_reversible,
    normalize_orientation,
    orientation_label,
    orientation_symbol,
    random_orientation,
    yes_no_draw,
)
from rune_collage import BADGE_GAP, BADGE_HEIGHT, PADDING, build_single_rune_card, build_spread_collage
from runes_data import NON_REVERSIBLE_RUNE_KEYS, RUNES
from year_rasklad import build_month_interpretation
from spread_engine_approved import build_unified_spread, build_unified_spread_pages


def test_non_reversible_runes_never_draw_reversed():
    for rune_key in NON_REVERSIBLE_RUNE_KEYS:
        assert normalize_orientation(rune_key, "rev") == "up"
        assert {random_orientation(rune_key) for _ in range(50)} == {"up"}
        assert orientation_label("rev", rune_key) == "необратимая"
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


def test_blank_rune_participates_and_returns_a_neutral_yes_no_answer():
    only_blank = [{"key": "wyrd", "name": "Пустая руна"}]
    assert draw_yes_no_rune(only_blank)["key"] == "wyrd"
    assert yes_no_draw("wyrd") == ("up", "unknown")
    answer = get_sphere_answer("wyrd", "premium", "relationships", "unknown")
    assert answer["answer_label"] == "Нет ясного ответа"
    assert answer["sphere_label"] == "Отношения"


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


def test_each_deck_keeps_a_cohesive_brightness_range():
    ranges = {"light": (0.78, 0.87), "dark": (0.025, 0.065), "premium": (0.58, 0.74)}
    for palette, (minimum, maximum) in ranges.items():
        paths = sorted(Path(palette).glob("*.jpg")) + sorted(Path(palette).glob("*.JPG"))
        assert len(paths) == 25
        for path in paths:
            with Image.open(path) as image:
                sample = image.convert("RGB").resize((1, 1))
                mean = sum(ImageStat.Stat(sample).mean) / (3 * 255)
            assert minimum <= mean <= maximum, f"{path} brightness {mean:.3f} is outside its deck"


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
    labels = ["прямое", "перевёрнутое", "необратимая"]
    collage_path = build_spread_collage(paths, "light", labels)
    with Image.open(collage_path) as collage:
        assert collage.width > collage.height
        assert collage.height == 820


def test_reversed_single_card_keeps_artwork_upright_and_adds_position_badge(tmp_path):
    source_path = tmp_path / "orientation.png"
    source = Image.new("RGB", (20, 40), "red")
    for y in range(20, 40):
        for x in range(20):
            source.putpixel((x, y), (0, 0, 255))
    source.save(source_path)

    result_path = build_single_rune_card(str(source_path), "light", "перевёрнутое")
    with Image.open(result_path) as result:
        artwork_top = PADDING + BADGE_HEIGHT + BADGE_GAP + 20
        pixel = result.getpixel((result.width // 2, artwork_top))
        assert pixel[0] > pixel[2]


def test_three_card_text_uses_past_present_and_conditional_future():
    draws = [
        ({"key": "fehu", "name": "Феху"}, "up"),
        ({"key": "uruz", "name": "Уруз"}, "up"),
        ({"key": "thurisaz", "name": "Турисаз"}, "up"),
    ]
    text = build_unified_spread("Что происходит?", draws, "light", "Дмитрий")
    assert "1️⃣ <b>Прошлое</b>\nᚱ <b>Феху</b>\n<i>прямое</i>" in text
    assert "2️⃣ <b>Настоящее</b>\nᚱ <b>Уруз</b>\n<i>прямое</i>" in text
    assert "3️⃣ <b>Будущее</b>\nᚱ <b>Турисаз</b>\n<i>прямое</i>" in text
    assert "<b>Если текущая траектория сохранится</b>" in text


def test_question_spheres_are_detected_and_generic_choice_does_not_override_domain():
    assert detect_question_sphere("Стоит ли менять работу?") == "work"
    assert detect_question_sphere("Вернётся ли бывший партнёр?") == "relationships"
    assert detect_question_sphere("Стоит ли брать кредит?") == "money"
    assert detect_question_sphere("Нужно ли идти к врачу?") == "health"
    assert detect_question_sphere("Когда будет результат?") == "timing"
    assert detect_question_sphere("Стоит ли соглашаться?") == "decision"
    assert detect_question_sphere("Мы обсудили поездку") == "decision"


def test_spread_uses_detected_sphere_and_is_split_from_the_beginning():
    draws = [
        ({"key": "fehu", "name": "Феху"}, "up"),
        ({"key": "uruz", "name": "Уруз"}, "up"),
        ({"key": "thurisaz", "name": "Турисаз"}, "up"),
    ]
    pages = build_unified_spread_pages("Что происходит на работе?", draws, "light", "Дмитрий")
    assert len(pages) == 3
    assert "Сфера" not in "\n".join(pages)
    assert "1️⃣ <b>Прошлое" in pages[0]
    assert "2️⃣ <b>Настоящее" in pages[1]
    assert "3️⃣ <b>Будущее" in pages[2]
    assert "Итог расклада" in pages[2]


def test_every_rune_deck_orientation_and_position_has_safe_spread_text():
    from rune_text_repository import get_rasklad_text

    for rune in RUNES:
        orientations = ("up", "rev") if is_reversible(rune["key"]) else ("up",)
        for palette in ("light", "dark", "premium"):
            for orientation in orientations:
                for position in ("past", "present", "future"):
                    assert get_rasklad_text(rune["key"], palette, orientation, position)["text"].strip()


def test_every_daily_reading_fits_photo_caption_and_uses_shared_hierarchy():
    from product_runtime import build_daily_card_text

    for rune in RUNES:
        orientations = ("up", "rev") if is_reversible(rune["key"]) else ("up",)
        for palette in ("light", "dark", "premium"):
            for orientation in orientations:
                text = build_daily_card_text(
                    "Имя не должно попасть в ответ",
                    palette,
                    rune,
                    orientation,
                    "2026-07-18",
                    12,
                )
                assert len(text) <= 1024
                assert "Имя не должно попасть в ответ" not in text
                assert text.startswith("🌞 <b>Руна дня</b>\n\nᚱ <b>")
                assert "🔎 <b>Основной смысл</b>" in text
                assert "🧭 <b>Ориентир на день</b>" in text


def test_all_sphere_pages_fit_telegram_message_limit():
    draws = [
        ({"key": "fehu", "name": "Феху"}, "up"),
        ({"key": "uruz", "name": "Уруз"}, "rev"),
        ({"key": "thurisaz", "name": "Турисаз"}, "up"),
    ]
    questions = (
        "Вернётся ли бывший партнёр?",
        "Стоит ли менять работу?",
        "Стоит ли брать кредит?",
        "Что происходит со здоровьем?",
        "Когда будет результат?",
        "Как поступить?",
    )
    for palette in ("light", "dark", "premium"):
        for question in questions:
            pages = build_unified_spread_pages(question, draws, palette, "Дмитрий")
            assert len(pages) == 3
            assert all(0 < len(page) <= 1000 for page in pages)


def test_legacy_spread_address_is_normalized_to_informal_voice():
    from rune_text_repository import _normalize_user_address

    text = _normalize_user_address("Это заставит вас вернуться к вашей опоре и быть рядом с вами.")
    assert text == "Это заставит тебя вернуться к твоей опоре и быть рядом с тобой."
