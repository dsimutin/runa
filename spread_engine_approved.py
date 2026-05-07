from html import escape
from typing import Any

from rune_decks_approved import get_deck_meaning

TOPIC_KEYWORDS = {
    "love": ["вместе", "отнош", "люб", "чувств", "партнер", "партнёр", "бывш", "верн", "брак", "пара", "скуч", "напиш"],
    "work": ["работ", "карьер", "проект", "началь", "коллег", "бизнес", "клиент", "контракт"],
    "money": ["деньг", "финанс", "доход", "зарплат", "куп", "прод", "долг", "оплат", "расход", "прибыль"],
    "choice": ["стоит", "выбор", "выбрать", "или", "решить", "соглас", "отказ", "уйти", "остаться", "как поступ", "надо ли"],
    "conflict": ["ссор", "конфликт", "обид", "давит", "манипул", "претенз", "напряж", "руга", "спор"],
    "future": ["будет", "получится", "ждет", "ждёт", "перспектив", "исход", "результат", "сложится"],
}

GROUPS = {
    "resource": {"fehu", "othala", "uruz", "berkana"},
    "tension": {"nauthiz", "hagalaz", "thurisaz", "isa"},
    "people": {"gebo", "mannaz", "ehwaz", "laguz"},
    "movement": {"raido", "inguz", "dagaz", "jera"},
    "clarity": {"ansuz", "kenaz", "perthro", "sowilo"},
    "will": {"teiwaz", "algiz", "eihwaz"},
}

RUNE_NAMES = {"fehu":"Феху","uruz":"Уруз","thurisaz":"Турисаз","ansuz":"Ансуз","raido":"Райдо","kenaz":"Кеназ","gebo":"Гебо","wunjo":"Вуньо","hagalaz":"Хагалаз","nauthiz":"Наутиз","isa":"Иса","jera":"Йера","eihwaz":"Эйваз","perthro":"Перт","algiz":"Альгиз","sowilo":"Соулу","teiwaz":"Тейваз","berkana":"Беркана","ehwaz":"Эваз","mannaz":"Манназ","laguz":"Лагуз","inguz":"Ингуз","dagaz":"Дагаз","othala":"Отал"}


def detect_topic(question: str) -> str:
    q = (question or "").lower()
    scores = {topic: sum(1 for word in words if word in q) for topic, words in TOPIC_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else "general"


def rune_key(rune: dict[str, Any]) -> str:
    return (rune.get("key") or "").lower().strip()


def rune_name(rune: dict[str, Any]) -> str:
    return RUNE_NAMES.get(rune_key(rune), rune.get("name", "Руна"))


def group_of(key: str) -> str:
    for group, keys in GROUPS.items():
        if key in keys:
            return group
    return "other"


def short_sentence(text: str, limit: int = 230) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(".,;:") + "."


def intro_by_topic(topic: str) -> str:
    return {
        "love": "Сейчас в центре вопроса не красивые слова, а то, как между вами на самом деле движется тепло, внимание и ответственность.",
        "work": "В этой истории важны не только возможности, но и условия: кто за что отвечает, где есть отдача и где уже начинается перегруз.",
        "money": "Здесь всё лучше смотреть через деньги, силы и цену участия. Не по обещаниям, а по тому, что реально остаётся у вас на руках.",
        "choice": "Этот выбор нельзя смотреть только через желание. Важно понять, какой вариант вы выдержите не один день, а дальше.",
        "conflict": "Здесь уже есть напряжение, даже если его пытаются сгладить. Вопрос в том, где проходит граница и кто готов её уважать.",
        "future": "Ближайшее развитие зависит не от случайности, а от того, что уже повторяется сейчас. Именно это задаёт направление.",
    }.get(topic, "Сейчас важнее увидеть не отдельный знак, а общую линию: что держит вопрос, где он буксует и куда начинает двигаться.")


def bridge_text(groups: list[str], topic: str) -> str:
    s = set(groups)
    if "tension" in s and "people" in s:
        return "Главная связка здесь — между людьми и накопившимся напряжением. Внешне всё может выглядеть терпимо, но внутри уже становится понятно: прежний формат начинает выматывать."
    if "resource" in s and "tension" in s:
        return "Ресурсы и силы здесь быстро становятся главным вопросом. Если продолжать вкладываться без нормальной отдачи, дальше будет не развитие, а усталость."
    if "clarity" in s and "people" in s:
        return "Многое решит не догадка, а то, что станет понятно через слова, поступки и повторяющееся поведение. Надежду лучше проверять реальностью."
    if "movement" in s and "tension" in s:
        return "Есть движение, но оно идёт через сопротивление. Если не убрать источник напряжения, следующий шаг может оказаться вынужденным, а не свободным."
    if "will" in s and "people" in s:
        return "Здесь важно не раствориться в чужой реакции. Чем яснее ваша позиция, тем меньше шансов снова оказаться в роли того, кто всё удерживает один."
    if "clarity" in s and "movement" in s:
        return "Сначала приходит понимание, потом движение. Если попытаться ускориться до ясности, можно снова попасть в тот же круг."
    if topic == "love":
        return "В отношениях сейчас важнее смотреть не на отдельные тёплые моменты, а на общий ритм: есть ли движение с двух сторон или всё держится на вашем ожидании."
    return "Эти руны вместе показывают не разрозненные события, а одну линию: сначала становится видна причина, потом — цена прежнего поведения."


def final_text(topic: str, last_group: str) -> str:
    if topic == "love":
        return "Сейчас вам важнее смотреть не на редкие хорошие моменты, а на то, что повторяется постоянно."
    if topic == "work":
        return "Не берите на себя больше, пока не станет понятно, где ваша зона ответственности и какая будет отдача."
    if topic == "money":
        return "Сначала считайте цену решения, потом уже смотрите на обещанную выгоду."
    if topic == "choice":
        return "Сильнее тот вариант, после которого вам не придётся постоянно уговаривать себя."
    if topic == "conflict":
        return "Не усиливайте давление. Сначала верните границу, потом продолжайте разговор."
    if last_group == "tension":
        return "Если ничего не менять, вопрос начнёт сильнее забирать силы, чем давать движение."
    if last_group == "movement":
        return "Дальше будет движение, но лучше идти осознанно, а не по инерции."
    if last_group == "clarity":
        return "Главное — не отворачиваться от того, что уже стало очевидным."
    return "Сейчас нужен не резкий шаг, а честный взгляд на то, что уже стало повторяться."


def build_unified_spread(question: str, runes: list[dict[str, Any]], deck: str = "premium") -> str:
    topic = detect_topic(question)
    keys = [rune_key(r) for r in runes]
    groups = [group_of(k) for k in keys]
    meanings = [get_deck_meaning(k, deck, False) for k in keys]
    names = [rune_name(r) for r in runes]
    cards = " · ".join(escape(name) for name in names)
    safe_question = escape(short_sentence(question, 120))
    first = escape(short_sentence(meanings[0]["text"], 260))
    second = escape(short_sentence(meanings[1]["text"], 260))
    third = escape(short_sentence(meanings[2]["text"], 260))
    bridge = escape(bridge_text(groups, topic))
    finish = escape(final_text(topic, groups[2]))
    return f"🔮 <b>Расклад</b>\n\n<i>{safe_question}</i>\n\n<b>{cards}</b>\n\n{escape(intro_by_topic(topic))}\n\n{first}\n\n{second}\n\n{bridge}\n\n───\n\n{third}\n\n───\n\n<b>{finish}</b>"
