from pathlib import Path

import bot
import human_reading
import product_runtime_final
from product_runtime import product_yes_no_text
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
