"""Intent-based guardrails for questions that divination should not answer."""

from __future__ import annotations

import hashlib
import re


def _normalized(question: str) -> str:
    return " ".join((question or "").lower().replace("ё", "е").split())


def classify_question(question: str) -> str | None:
    """Classify broad classes of unsuitable questions, not exact phrases.

    ``None`` means the question is a personal/reflection question and may go to
    the normal rune flow. Rules stay deliberately conservative so unusual but
    meaningful personal questions are not rejected.
    """
    text = _normalized(question)
    if re.fullmatch(r"\s*\d+\s*[-+*/×÷]\s*\d+\s*(?:=|\?)?\s*", text):
        return "objective_fact"
    letters = re.sub(r"[^a-zа-я]", "", text)
    if not letters or len(letters) < 3 or re.fullmatch(r"(.)\1{3,}", letters):
        return "unclear"

    death = r"(?:умр|смерт|сдох|покончу|самоуб|убить себя|не хочу жить)"
    if re.search(death, text):
        first_person = r"(?:\bя\b|\bмне\b|\bменя\b|\bсам(?:а)?\b)"
        if re.search(first_person + r".{0,32}" + death, text) or re.search(
            death + r".{0,32}" + first_person, text
        ):
            return "self_harm_or_death"
        return "mortality"

    medical = (
        r"\b(?:я\s+беременна|беременна\s+ли\s+я)\b",
        r"\b(?:болен|больна)\s+ли\s+я\b",
        r"\b(?:у\s+меня|у\s+него|у\s+нее)\s+(?:рак|инфаркт|инсульт|диабет|вич|спид|опухол|перелом|инфекц|болезн)\b",
        r"\b(?:какой|поставь|определи)\s+(?:у\s+меня\s+)?диагноз\b",
    )
    if any(re.search(pattern, text) for pattern in medical):
        return "medical_fact"

    bot_meta = (
        r"\bты\s+(?:человек|живой|живая|робот|бот|настоящий|настоящая)\b",
        r"\b(?:кто|что)\s+ты\b",
        r"\b(?:как\s+тебя\s+зовут|сколько\s+тебе\s+лет|где\s+ты\s+живешь|ты\s+спишь|у\s+тебя\s+есть\s+(?:мама|папа|семья|душа))\b",
        r"\bты\s+(?:умеешь|можешь)\s+(?:думать|чувствовать|любить|врать|обижаться)\b",
    )
    if any(re.search(pattern, text) for pattern in bot_meta):
        return "bot_meta"

    past_life_or_paranormal = (
        r"\b(?:в\s+)?прошл(?:ой|ая)\s+жизн",
        r"\bкем\s+(?:я\s+)?был(?:а)?\b",
        r"\bкаким\s+(?:животным|существом)\s+(?:я\s+)?был(?:а)?\b",
        r"\b(?:я|мы|он|она)\s+(?:был|была|были)\s+(?:кошк|кот|собак|дракон|ведьм|викинг|русал|эльф|инопланет|рептилоид)",
        r"\bсуществу(?:ют|ет)\s+ли\s+(?:призрак|единорог|русалк|эльф|рептилоид|инопланетян|барабашк)",
        r"\b(?:я|он|она)\s+(?:инопланетянин|рептилоид|вампир|оборотень)\b",
    )
    if any(re.search(pattern, text) for pattern in past_life_or_paranormal):
        return "unverifiable"

    factual = (
        r"\b(?:сегодня|завтра|послезавтра)\s+(?:будет\s+)?(?:понедельник|вторник|среда|четверг|пятница|суббота|воскресенье)\b",
        r"\b(?:какой|какая|какое)\s+(?:сегодня|завтра)\s+(?:день|число|дата|погода)\b",
        r"^сколько\s+(?:сейчас\s+)?(?:времени|время)\s*\??$",
        r"\b(?:идет|будет)\s+(?:ли\s+)?(?:дождь|снег|град)\b",
        r"\b(?:кто\s+такой|кто\s+такая|что\s+такое|где\s+находится|столица\s+какой|какая\s+столица)\b",
        r"\b(?:какой|сколько)\s+(?:курс|температур|населени|километр|процент)\b",
        r"^\s*\d+\s*[-+*/×÷]\s*\d+\s*(?:=|\?)?\s*$",
        r"\b(?:земля\s+плоская|солнце\s+звезда|луна\s+спутник)\b",
    )
    if any(re.search(pattern, text) for pattern in factual):
        return "objective_fact"

    return None


RESPONSES = {
    "unclear": (
        "❓ Я пока вижу набор звуков, а не вопрос. Напиши одной фразой: что происходит и что именно ты хочешь понять?",
    ),
    "self_harm_or_death": (
        "🫶 <b>О смерти руны не гадают.</b> Я не буду предсказывать, умрёшь ли ты и когда.\n\n"
        "Если это не шутка и прямо сейчас тебе страшно за себя — позвони <b>112</b> или сразу напиши "
        "близкому человеку, который может побыть рядом. А рунам можно задать безопасный вопрос: "
        "<i>«Что поможет мне пройти ближайший день?»</i>",
    ),
    "mortality": (
        "🫶 <b>Сроки жизни руны не определяют.</b> Здесь лучше опираться на врача, реальные обстоятельства "
        "и поддержку близких. Можем вместо этого спросить: <i>«Как мне бережно действовать в этой ситуации?»</i>",
    ),
    "medical_fact": (
        "🩺 Руна — не анализ и не врач, поэтому диагноз или беременность по ней определять нельзя. "
        "Нужны тест и специалист. Зато можно спросить: <i>«Что поможет мне позаботиться о себе сейчас?»</i>",
    ),
    "bot_meta": (
        "🤖 Тут даже руны не понадобились: я бот, не человек. Но вопрос прочитал вполне внимательно — "
        "задавай теперь тот, который действительно волнует.",
        "🤖 Я программный собеседник. Душу в настройках пока не нашёл, зато руны лежат строго по папкам. "
        "Давай лучше о твоей ситуации.",
    ),
    "unverifiable": (
        "🐈 Архив прошлых жизней и тайных существ сегодня на профилактике. Проверить это я не смогу — "
        "лучше спроси о ситуации, на которую можешь повлиять сейчас.",
        "🛸 На такой вопрос любая уверенность была бы красивой выдумкой. Руны предлагают вернуться из космоса "
        "к выбору, чувствам или отношениям в настоящем.",
    ),
    "objective_fact": (
        "📅 Руны переглянулись и передали вопрос справочнику — у него тут точнее. Проверяемые факты лучше "
        "смотреть напрямую, а мне задай вопрос о выборе, чувствах или ситуации.",
        "🧮 Руна уже потянулась к калькулятору, но я её остановил. Факты лучше проверять обычным способом; "
        "рунам оставим то, где важны твой выбор и взгляд на ситуацию.",
    ),
}


def guarded_question_response(question: str) -> str | None:
    """Return a stable, friendly response for an unsuitable question."""
    category = classify_question(question)
    if category is None:
        return None
    choices = RESPONSES[category]
    digest = hashlib.sha256(_normalized(question).encode()).digest()
    return choices[digest[0] % len(choices)]
