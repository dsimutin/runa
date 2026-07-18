import asyncio
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
    """Use the same sphere detector as the one-rune answer.

    Keeping one detector prevents the same question being treated as work in
    one product and as a generic choice in another.
    """
    from rune_text_repository import detect_question_sphere

    return {
        "relationships": "love",
        "work": "work",
        "money": "money",
        "health": "health",
        "timing": "timing",
        "decision": "choice",
    }[detect_question_sphere(question)]


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
        "health": "В центре вопроса — самочувствие и запас сил. Руны здесь помогают увидеть нагрузку и направление заботы о себе, но не заменяют врача и диагностику.",
        "timing": "В вопросе о сроках важнее увидеть, что ускоряет или задерживает развитие. Руны показывают динамику, а не гарантированную календарную дату.",
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
    if topic == "health":
        return "Отнесись к сигналам тела серьёзно; при симптомах опирайся на врача, а не только на символический расклад."
    if topic == "timing":
        return "Срок прояснится по движению ситуации: смотри, исчезают ли задержки и появляются ли реальные шаги."
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
    from rune_text_repository import get_rasklad_text, orientation_label
    orientation_labels = [orientation_label(o, k) for k, o in zip(keys, orientations)]
    position_descriptions = orientation_labels
    safe_question = escape(short_sentence(question, 120))
    position_keys = ("past", "present", "future")
    position_labels = ("Прошлое", "Настоящее", "Будущее")
    position_texts = []
    for key, orientation, position, label in zip(keys, orientations, position_keys, position_labels):
        raw = get_rasklad_text(key, deck, orientation, position)["text"]
        raw = re.sub(rf"^{label}:\s*", "", raw, flags=re.IGNORECASE)
        position_texts.append(escape(short_sentence(raw, 360)))
    first, second, third = position_texts
    bridge = escape(bridge_text(groups, topic))
    finish = escape(final_text(topic, groups[2]))
    header = "🔮 <b>Расклад на три руны</b>"
    person_line = f"\n<b>{escape(name)}</b>" if name else ""
    from rune_text_repository import SPHERE_LABELS, detect_question_sphere
    sphere_label = escape(SPHERE_LABELS[detect_question_sphere(question)])
    return (
        f"{header}{person_line}\n\n❓ <b>Вопрос</b>\n<i>«{safe_question}»</i>\n\n"
        f"🎯 <b>Сфера</b>\n{sphere_label}\n\n"
        f"{escape(intro_by_topic(topic))}\n\n"
        f"1️⃣ <b>Прошлое</b>\n{escape(names[0])} · {position_descriptions[0]}\n{first}\n\n"
        f"2️⃣ <b>Настоящее</b>\n{escape(names[1])} · {position_descriptions[1]}\n{second}\n\n"
        f"🔗 <b>Связь между рунами</b>\n{bridge}\n\n"
        f"3️⃣ <b>Будущее</b>\n{escape(names[2])} · {position_descriptions[2]}\n"
        f"<i>Если текущая траектория сохранится:</i>\n{third}\n\n"
        f"───\n\n{finish}"
    )


def build_unified_spread_pages(
    question: str,
    rune_draws: list[tuple[dict[str, Any], str]],
    deck: str = "premium",
    name: str = "",
) -> list[str]:
    """Split the reading into short, navigable pages for Telegram."""
    full = build_unified_spread(question, rune_draws, deck, name)
    markers = ("1️⃣ <b>Прошлое", "2️⃣ <b>Настоящее", "3️⃣ <b>Будущее", "───")
    starts = [full.index(marker) for marker in markers]
    header = full[:starts[0]].rstrip()
    past = full[starts[0]:starts[1]].rstrip()
    present = full[starts[1]:starts[2]].rstrip()
    future = full[starts[2]:starts[3]].rstrip()
    summary = full[starts[3]:].replace("───", "🧭 <b>Итог расклада</b>", 1).strip()
    # The conclusion belongs to the projected trajectory: showing it together
    # with the third rune makes the reading finish naturally without a separate
    # fourth screen that can feel detached from the future it summarises.
    return [f"{header}\n\n{past}", present, f"{future}\n\n{summary}"]


def spread_page_markup(token: str, page: int, total: int):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("← Назад", callback_data=f"spread_page:{token}:{page - 1}"))
    if page + 1 < total:
        buttons.append(InlineKeyboardButton("Далее →", callback_data=f"spread_page:{token}:{page + 1}"))
    rows = [buttons] if buttons else []
    rows.append([InlineKeyboardButton("↩️ Меню", callback_data="reading:menu")])
    return InlineKeyboardMarkup(rows)


async def spread_page_callback(update, context) -> None:
    from telegram.error import TelegramError

    query = update.callback_query
    if not query:
        return
    match = re.fullmatch(r"spread_page:([a-f0-9]+):(\d+)", query.data or "")
    if not match:
        return
    token, page_raw = match.groups()
    stored = context.user_data.get("spread_pages") or {}
    if stored.get("token") != token:
        await query.answer("Этот расклад уже устарел. Сделай новый.", show_alert=True)
        return
    pages = stored.get("pages") or []
    page = int(page_raw)
    if page >= len(pages):
        await query.answer("Страница не найдена.", show_alert=True)
        return
    await query.answer()
    try:
        if stored.get("media"):
            await query.edit_message_caption(
                caption=pages[page],
                parse_mode="HTML",
                reply_markup=spread_page_markup(token, page, len(pages)),
            )
        else:
            await query.edit_message_text(
                pages[page],
                parse_mode="HTML",
                reply_markup=spread_page_markup(token, page, len(pages)),
            )
    except TelegramError:
        # An old Telegram client/message can occasionally reject editing.
        # Continue the reading in a new message instead of losing the page.
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text=pages[page],
            parse_mode="HTML",
            reply_markup=spread_page_markup(token, page, len(pages)),
        )


async def send_approved_rasklad(update, context, question: str) -> None:
    import bot
    import time
    from telegram import ReplyKeyboardRemove

    from question_guard import guarded_question_response
    guarded_response = guarded_question_response(question)
    if guarded_response:
        await bot.send_private_or_group(update, context, guarded_response)
        return

    started_at = time.perf_counter()
    status_message = None
    if update.effective_user:
        try:
            status_message = await context.bot.send_message(
                chat_id=update.effective_user.id,
                text="🔮 Подбираю три руны и собираю расклад…",
                reply_markup=ReplyKeyboardRemove(),
            )
        except Exception:
            bot.logger.debug("Could not send spread progress message", exc_info=True)
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
        if status_message:
            try:
                await status_message.delete()
            except Exception:
                pass
        await bot.send_missing_image_error(update, context, rune_draws[image_paths.index(None)][0], deck)
        return
    from rune_collage import build_spread_collage
    from rune_text_repository import orientation_label
    collage_labels = [orientation_label(orientation, rune["key"]) for rune, orientation in rune_draws]
    text_started_at = time.perf_counter()
    pages = build_unified_spread_pages(question, rune_draws, deck, bot.user_name(update))
    text_seconds = time.perf_counter() - text_started_at
    collage_started_at = time.perf_counter()
    try:
        image_path = await asyncio.to_thread(
            build_spread_collage, image_paths, deck, collage_labels
        )
    except Exception:
        bot.logger.exception("Failed to build three-rune collage; sending text fallback")
        image_path = None
    collage_seconds = time.perf_counter() - collage_started_at
    send_started_at = time.perf_counter()
    import secrets
    token = secrets.token_hex(4)
    media_pages = bool(
        image_path and all(len(page) <= bot.MAX_PHOTO_CAPTION_LENGTH for page in pages)
    )
    context.user_data["spread_pages"] = {
        "token": token,
        "pages": pages,
        "media": media_pages,
    }
    if status_message:
        try:
            await status_message.delete()
        except Exception:
            bot.logger.debug("Could not remove spread progress message", exc_info=True)
    try:
        if media_pages:
            await bot.send_cached_photo(
                context.bot.send_photo,
                image_path,
                chat_id=update.effective_user.id,
                caption=pages[0],
                parse_mode="HTML",
                reply_markup=spread_page_markup(token, 0, len(pages)),
            )
        else:
            if image_path:
                await bot.send_cached_photo(
                    context.bot.send_photo,
                    image_path,
                    chat_id=update.effective_user.id,
                )
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text=pages[0],
                parse_mode="HTML",
                reply_markup=spread_page_markup(token, 0, len(pages)),
            )
    except Exception:
        bot.logger.exception("Failed to send paginated spread; sending plain fallback")
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text=bot.strip_html(build_unified_spread(question, rune_draws, deck, bot.user_name(update))),
            reply_markup=bot.main_keyboard_for(update.effective_user.id),
        )
    finally:
        bot.logger.info(
            "Three-rune spread delivered total=%.2fs text=%.3fs collage=%.3fs telegram=%.2fs",
            time.perf_counter() - started_at,
            text_seconds,
            collage_seconds,
            time.perf_counter() - send_started_at,
        )
