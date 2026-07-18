from pathlib import Path

import bot
import human_reading
import product_runtime_final
import premium_subscription
from product_runtime import product_yes_no_text
from product_runtime import build_daily_card_text
from question_guard import classify_question, guarded_question_response
from premium_subscription import PREMIUM_BENEFITS


def test_help_does_not_advertise_moon_phase():
    assert "лунная фаза" not in bot.short_help().lower()


def test_payment_details_use_compact_copyable_format():
    assert "<pre>" not in human_reading.HUMAN_READING_TEXT
    assert "<code>5536 9141 3069 4684</code>" in human_reading.HUMAN_READING_TEXT
    assert "<code>+7 999 221-86-89</code>" in human_reading.HUMAN_READING_TEXT

    premium_text = product_runtime_final.premium_card_payment_text()
    assert "<pre>" not in premium_text
    assert "<code>5536 9141 3069 4684</code>" in premium_text
    assert "<code>+7 999 221-86-89</code>" in premium_text


def test_trial_copy_does_not_claim_every_premium_feature():
    assert "со всеми функциями" not in PREMIUM_BENEFITS.lower()


def test_yes_no_menu_asks_for_own_question_without_suggestions():
    source = Path(product_runtime_final.__file__).read_text(encoding="utf-8")
    branch = source[source.index('if text in {"❓ Вопрос"'):source.index('if text == "🔮 Расклад"')]
    assert "TRIGGER_QUESTIONS" not in branch
    assert "Напиши свой вопрос" in branch


def test_question_flows_hide_non_persistent_reply_keyboard():
    keyboard = product_runtime_final.build_main_keyboard(352086154)
    assert keyboard.is_persistent is False

    source = Path(product_runtime_final.__file__).read_text(encoding="utf-8")
    question_branch = source[
        source.index('if text in {"❓ Вопрос"') : source.index('if text == "🔮 Расклад"')
    ]
    spread_branch = source[
        source.index('if text == "🔮 Расклад"') : source.index(
            'if text == product_runtime.SETTINGS_BUTTON'
        )
    ]
    assert "ReplyKeyboardRemove()" in question_branch
    assert "ReplyKeyboardRemove()" in spread_branch


def test_relationship_callback_accepts_two_part_button_payload():
    source = Path(product_runtime_final.__file__).read_text(encoding="utf-8")
    branch = source[
        source.index("async def relationship_type_callback") : source.index(
            "async def trigger_question_callback"
        )
    ]
    assert 'len(parts) >= 2' in branch
    assert 'context.user_data.get("relationship_person", "")' in branch


def test_trial_menu_keeps_settings_and_is_not_persistent(monkeypatch):
    monkeypatch.setattr(premium_subscription, "get_premium_state", lambda _user_id: (True, True))
    keyboard = product_runtime_final.build_main_keyboard(123)
    labels = {button.text for row in keyboard.keyboard for button in row}
    assert "⚙️ Настройки" in labels
    assert "🗓 Расклад на год" in labels
    assert keyboard.is_persistent is False


def test_all_main_menu_buttons_have_text_routes(monkeypatch):
    routed_labels = {
        "🌞 Руна дня",
        "❓ Вопрос (да/нет)",
        "🔮 Расклад",
        "🕯 Личный расклад",
        "🗓 Расклад на год",
        "👥 Взаимоотношения",
        "💠 Премиум",
        "⚙️ Настройки",
        "📜 Значения рун",
        "ℹ️ Помощь",
    }
    for premium_state in ((False, False), (True, True), (True, False)):
        monkeypatch.setattr(
            premium_subscription,
            "get_premium_state",
            lambda _user_id, state=premium_state: state,
        )
        keyboard = product_runtime_final.build_main_keyboard(123)
        labels = {button.text for row in keyboard.keyboard for button in row}
        assert labels <= routed_labels


def test_every_inline_button_family_has_a_registered_handler():
    source = Path(product_runtime_final.__file__).read_text(encoding="utf-8")
    expected_patterns = (
        r'^onboarding:',
        r'^settings:deck:',
        r'^spread_page:',
        r'^reading:menu$',
        r'^trigger_q:',
        r'^rune_info:',
        r'^weekly_day:',
        r'^weekly_rasklad:',
        r'^year_rune:|^year_rasklad_back:',
        r'^rel_type:',
        r'^human_reading:',
        r'^premium:',
        r'^op:',
    )
    for pattern in expected_patterns:
        assert f'pattern=r"{pattern}"' in source


def test_relationship_reading_uses_clear_person_labels():
    source = Path(product_runtime_final.__file__).with_name("relationship_rasklad.py").read_text(
        encoding="utf-8"
    )
    assert 'their_label = "Они"' not in source
    assert 'their_label = "Они в работе"' not in source
    assert "Твоя позиция" in source
    assert "позиция в отношениях" in source
    assert "Динамика между вами" in source
    assert "Ты ↔" in source


def test_question_guard_handles_facts_meta_past_lives_and_death_safely():
    objective_facts = (
        "Завтра воскресенье?",
        "Сколько сейчас времени?",
        "Какая столица Франции?",
        "2 + 2?",
        "Земля плоская?",
    )
    assert all(classify_question(question) == "objective_fact" for question in objective_facts)
    assert classify_question("Ты человек?") == "bot_meta"
    assert classify_question("Сколько тебе лет?") == "bot_meta"
    assert classify_question("Я был кошкой?") == "unverifiable"
    assert classify_question("Кем я была в прошлой жизни?") == "unverifiable"
    assert classify_question("Я беременна?") == "medical_fact"
    assert classify_question("У меня рак?") == "medical_fact"
    death = guarded_question_response("Я умру завтра?")
    assert "не буду предсказывать" in death.lower()
    assert "112" in death
    valid_questions = (
        "Стоит ли мне менять работу?",
        "Он вернётся?",
        "Что происходит в наших отношениях?",
        "Сколько времени мне ждать его решения?",
        "Как мне позаботиться о здоровье?",
        "Будет ли у меня новая работа?",
    )
    assert all(classify_question(question) is None for question in valid_questions)


def test_long_answers_are_split_at_paragraphs_within_telegram_limit():
    text = "\n\n".join(f"<b>Раздел {index}</b>\n" + "слово " * 220 for index in range(8))
    pages = bot.split_telegram_text(text)
    assert len(pages) > 1
    assert all(len(page) <= bot.MAX_TELEGRAM_PAGE_LENGTH for page in pages)
    assert "Раздел 0" in pages[0]
    assert "Раздел 7" in pages[-1]


def test_yes_no_question_is_html_escaped():
    text = product_yes_no_text(
        "<Дима>",
        "Я <прав?>",
        {"name": "Феху"},
        "прямое",
        {
            "palette": "light",
            "answer_label": "Да",
            "sphere_label": "Решение",
            "short_desc": "Кратко",
            "answer": "Да.",
        },
    )
    assert "&lt;Дима&gt;" in text
    assert "Я &lt;прав?&gt;" in text


def test_daily_card_uses_consistent_sections_without_random_headlines():
    text = build_daily_card_text(
        "Дмитрий", "light", {"key": "dagaz", "name": "Дагаз"}, "up", "2026-07-18", 2
    )
    assert text.startswith("🌞 <b>Руна дня</b>\n<b>Дмитрий</b> · Дагаз · необратимая")
    assert "🔎 <b>Основной смысл</b>" in text
    assert "❔ <b>Вопрос для размышления</b>" in text
    assert "🧭 <b>Ориентир на день</b>" in text
    assert "сегодняшний знак" not in text.lower()
    assert "Будь готовы" not in text


def test_yes_no_answer_uses_consistent_sections():
    text = product_yes_no_text(
        "Дмитрий",
        "Стоит ли менять работу?",
        {"name": "Феху"},
        "прямое",
        {
            "answer_label": "Да",
            "sphere_label": "Работа",
            "short_desc": "Появляется ресурс.",
            "answer": "Да. Можно действовать.",
        },
    )
    assert text.startswith("❓ <b>Ответ на вопрос</b>")
    assert "🔎 <b>Что показывает руна</b>" in text
    assert "✅ <b>Ответ</b>" in text


def test_reading_uses_compact_inline_menu_instead_of_large_reply_keyboard():
    button = bot.READING_KEYBOARD.inline_keyboard[0][0]
    assert button.text == "↩️ Меню"
    assert button.callback_data == "reading:menu"
