"""Friendly guardrails for questions that should not be answered by divination."""

from __future__ import annotations

import re


def guarded_question_response(question: str) -> str | None:
    """Return a user-facing response when drawing a rune would be misleading.

    The rules intentionally cover only clear cases. Ambiguous personal questions
    continue to the normal reading instead of being over-filtered.
    """
    normalized = " ".join((question or "").lower().replace("ё", "е").split())
    if not normalized:
        return "❓ Напиши вопрос целиком — одной фразы достаточно."

    death_words = r"(?:умр|смерт|сдох|покончу|самоуб|убить себя|не хочу жить)"
    if re.search(death_words, normalized):
        if re.search(r"(?:я|мне|меня|сам|сама).{0,24}" + death_words, normalized) or re.search(
            death_words + r".{0,24}(?:я|мне|меня)", normalized
        ):
            return (
                "🫶 <b>О смерти руны не гадают.</b> Я не буду предсказывать, умрёшь ли ты и когда.\n\n"
                "Если это не шутка и прямо сейчас тебе страшно за себя — позвони <b>112</b> "
                "или сразу напиши близкому человеку, который может побыть рядом. "
                "А рунам можно задать безопасный вопрос: <i>«Что поможет мне пройти ближайший день?»</i>"
            )
        return (
            "🫶 <b>Сроки жизни руны не определяют.</b> Здесь лучше опираться на врача, "
            "реальные обстоятельства и поддержку близких. Можем вместо этого спросить: "
            "<i>«Как мне бережно действовать в этой ситуации?»</i>"
        )

    if re.search(r"\bты\s+(?:человек|живой|живая|робот|бот)\b", normalized):
        return (
            "🤖 Тут даже руны не понадобились: я бот, не человек. "
            "Но вопрос прочитал вполне внимательно — задавай теперь тот, который действительно волнует."
        )

    if re.search(r"\b(?:я|мы|он|она)\s+(?:был|была|были)\s+(?:кошк|кот|собак|дракон|ведьм|викинг)", normalized):
        return (
            "🐈 Архив прошлых жизней сегодня на профилактике. Доказать кошку не смогу — "
            "но подозрительную любовь к коробкам можешь учесть самостоятельно. "
            "Лучше спроси о ситуации, на которую можешь повлиять сейчас."
        )

    factual_patterns = (
        r"\b(?:сегодня|завтра|послезавтра)\s+(?:будет\s+)?(?:понедельник|вторник|среда|четверг|пятница|суббота|воскресенье)\b",
        r"\bсколько\s+(?:сейчас\s+)?(?:времени|время)\b",
        r"\bкакая\s+(?:сегодня|завтра)\s+(?:дата|погода)\b",
        r"\b(?:идет|будет)\s+(?:ли\s+)?(?:дождь|снег)\b",
    )
    if any(re.search(pattern, normalized) for pattern in factual_patterns):
        return (
            "📅 Руны переглянулись и передали вопрос календарю — у него тут точнее. "
            "Проверяемые факты лучше смотреть напрямую, а мне задай вопрос о выборе, чувствах или ситуации."
        )

    return None
