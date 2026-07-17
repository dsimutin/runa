from html import escape
import re
from typing import Any

TOPIC_KEYWORDS = {
    "love": ["вместе", "отнош", "люб", "чувств", "партнер", "партнёр", "бывш", "верн", "брак", "пара", "скуч", "напиш"],
    "work": ["работ", "карьер", "проект", "началь", "коллег", "бизнес", "клиент", "контракт"],
    "money": ["деньг", "финанс", "доход", "зарплат", "куп", "прод", "долг", "оплат", "расход", "прибыль"],
    "choice": ["стоит", "выбор", "выбрать", "или", "решить", "соглас", "отказ", "уйти", "остаться", "как поступ", "надо ли"],
    "conflict": ["ссор", "конфликт", "обид", "давит", "манипул", "претенз", "напряж", "руга", "спор"],
    "future": ["будет", "получится", "ждет", "ждёт", "перспектив", "исход", "результат", "сложится"],
}

GROUPS = {
    "resource": {"fehu", "othala", "uruz", "berkano"},
    "tension": {"nauthiz", "hagalaz", "thurisaz", "isa"},
    "people": {"gebo", "mannaz", "ehwaz", "laguz"},
    "movement": {"raido", "ingwaz", "dagaz", "jera"},
    "clarity": {"ansuz", "kenaz", "perthro", "sowilo"},
    "will": {"tiwaz", "algiz", "eihwaz"},
}

RUNE_NAMES = {"fehu":"Феху","uruz":"Уруз","thurisaz":"Турисаз","ansuz":"Ансуз","raido":"Райдо","kenaz":"Кеназ","gebo":"Гебо","wunjo":"Вуньо","hagalaz":"Хагалаз","nauthiz":"Наутиз","isa":"Иса","jera":"Йера","eihwaz":"Эйваз","perthro":"Перт","algiz":"Альгиз","sowilo":"Соулу","tiwaz":"Тейваз","berkano":"Беркана","ehwaz":"Эваз","mannaz":"Манназ","laguz":"Лагуз","ingwaz":"Ингуз","dagaz":"Дагаз","othala":"Отал"}


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
        "money": "Здесь всё лучше смотреть через деньги, силы и цену участия. Не по обещаниям, а по тому, что реально остаётся у тебя на руках.",
        "choice": "Этот выбор нельзя смотреть только через желание. Важно понять, какой вариант ты выдержишь не один день, а дальше.",
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
        return "Здесь важно не раствориться в чужой реакции. Чем яснее твоя позиция, тем меньше шансов снова оказаться в роли того, кто всё удерживает один."
    if "clarity" in s and "movement" in s:
        return "Сначала приходит понимание, потом движение. Если попытаться ускориться до ясности, можно снова попасть в тот же круг."
    if topic == "love":
        return "В отношениях сейчас важнее смотреть не на отдельные тёплые моменты, а на общий ритм: есть ли движение с двух сторон или всё держится на твоём ожидании."
    return "Эти руны вместе показывают не разрозненные события, а одну линию: сначала становится видна причина, потом — цена прежнего поведения."


def final_text(topic: str, last_group: str) -> str:
    if topic == "love":
        return "Сейчас тебе важнее смотреть не на редкие хорошие моменты, а на то, что повторяется постоянно."
    if topic == "work":
        return "Не бери на себя больше, пока не станет понятно, где твоя зона ответственности и какая будет отдача."
    if topic == "money":
        return "Сначала считай цену решения, потом уже смотри на обещанную выгоду."
    if topic == "choice":
        return "Сильнее тот вариант, после которого тебе не придётся постоянно уговаривать себя."
    if topic == "conflict":
        return "Не усиливай давление. Сначала верни границу, потом продолжай разговор."
    if last_group == "tension":
        return "Если ничего не менять, вопрос начнёт сильнее забирать силы, чем давать движение."
    if last_group == "movement":
        return "Дальше будет движение, но лучше идти осознанно, а не по инерции."
    if last_group == "clarity":
        return "Главное — не отворачиваться от того, что уже стало очевидным."
    return "Сейчас нужен не резкий шаг, а честный взгляд на то, что уже стало повторяться."


def build_unified_spread(question: str, rune_draws: list[tuple[dict[str, Any], str]], deck: str = "premium", name: str = "") -> str:
    """rune_draws: list of (rune_dict, orientation) — orientation is 'up' or 'rev'.

    Orientation and temporal position both change the reading. Each card uses
    its dedicated past/present/future text, and the future is framed as a
    trajectory rather than a fixed prediction.

    `name`, if given, is used once in the header only — deliberately not
    threaded through every line, to avoid the message reading like it's
    performing familiarity rather than actually being personal.
    """
    runes = [r for r, _ in rune_draws]
    orientations = [o for _, o in rune_draws]
    topic = detect_topic(question)
    keys = [rune_key(r) for r in runes]
    groups = [group_of(k) for k in keys]
    names = [rune_name(r) for r in runes]
    from rune_text_repository import get_rasklad_text, orientation_symbol
    arrows = [orientation_symbol(k, o) for k, o in zip(keys, orientations)]
    position_names = ("Прошлое", "Настоящее", "Будущее")
    cards = " · ".join(
        f"{position}: {escape(name_)} {arrow}"
        for position, name_, arrow in zip(position_names, names, arrows)
    )
    safe_question = escape(short_sentence(question, 120))
    position_keys = ("past", "present", "future")
    position_texts = []
    for key, orientation, position, label in zip(keys, orientations, position_keys, position_names):
        raw = get_rasklad_text(key, deck, orientation, position)["text"]
        raw = re.sub(rf"^{label}:\s*", "", raw, flags=re.IGNORECASE)
        position_texts.append(escape(short_sentence(raw, 360)))
    first, second, third = position_texts
    bridge = escape(bridge_text(groups, topic))
    finish = escape(final_text(topic, groups[2]))
    header = f"🔮 <b>{escape(name)}, расклад</b>" if name else "🔮 <b>Расклад</b>"
    return (
        f"{header}\n\n<i>{safe_question}</i>\n\n<b>{cards}</b>\n\n"
        f"{escape(intro_by_topic(topic))}\n\n"
        f"1️⃣ <b>Прошлое — {escape(names[0])} {arrows[0]}</b>\n{first}\n\n"
        f"2️⃣ <b>Настоящее — {escape(names[1])} {arrows[1]}</b>\n{second}\n\n"
        f"{bridge}\n\n"
        f"3️⃣ <b>Будущее — {escape(names[2])} {arrows[2]}</b>\n"
        f"<i>Если текущая траектория сохранится:</i> {third}\n\n"
        f"───\n\n<b>{finish}</b>"
    )


async def send_approved_rasklad(update, context, question: str) -> None:
    import bot

    chat = update.effective_chat
    if chat:
        try:
            await context.bot.send_chat_action(chat_id=chat.id, action="typing")
        except Exception:
            pass
    deck = bot.get_user_palette(update) or "premium"
    if deck not in {"light", "dark", "premium"}:
        deck = "premium"
    from rune_text_repository import draw_distinct_runes_with_orientations
    rune_draws = draw_distinct_runes_with_orientations(bot.RUNES, 3)
    image_paths = [bot.get_rune_image_path(rune, deck) for rune, _ in rune_draws]
    if not all(image_paths):
        await bot.send_missing_image_error(update, context, rune_draws[image_paths.index(None)][0], deck)
        return
    from rune_collage import build_spread_collage
    image_path = build_spread_collage(image_paths, deck)
    text = build_unified_spread(question, rune_draws, deck, bot.user_name(update))
    await bot.send_private_or_group(update, context, text, image_path=image_path, reading_mode=True)
