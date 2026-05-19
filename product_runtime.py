import asyncio
import hashlib
import random
from datetime import date

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import CallbackQueryHandler, ContextTypes

import bot
from database import set_user_palette
from human_reading import HUMAN_READING_BUTTON, HUMAN_READING_TEXT
from rune_states import ALT_RATE, alt_meaning
from runes_data import RUNES, get_rune_by_name
from runes_interpretations import get_rune_day_text

STATE_WAITING_HUMAN = "waiting_human"
SETTINGS_BUTTON = "⚙️ Настройки"
QUESTION_BUTTON = "❓ Вопрос (да/нет)"
OLD_QUESTION_BUTTONS = {"❓ Вопрос", "❓ Задать вопрос", QUESTION_BUTTON}
PALETTE_NAMES = {"light": "Светлая", "dark": "Тёмная", "premium": "Премиум"}

bot.DECK_DIRS = {"light": "light", "dark": "dark", "premium": "premium"}

bot.MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [["🌞 Руна дня", QUESTION_BUTTON], ["🔮 Расклад", HUMAN_READING_BUTTON], [SETTINGS_BUTTON, "ℹ️ Помощь"]],
    resize_keyboard=True,
    is_persistent=True,
)

bot.ONBOARDING_QUESTIONS = [
    {"text": "Ты входишь в незнакомое пространство. Что считываешь первым?", "a": "Атмосферу, свет, воздух, внутреннее ощущение", "b": "Границы, правила, риски и кто управляет ситуацией", "c": "Детали, символы, скрытый смысл и общее напряжение"},
    {"text": "Когда внутри нет ясности, что тебе ближе?", "a": "Пауза и мягкое прояснение", "b": "Прямой ответ и действие", "c": "Глубокий разбор, где важны нюансы и подтекст"},
    {"text": "Какой образ сильнее откликается сейчас?", "a": "Тёплый луч на закрытой двери", "b": "Ключ в тёмной комнате", "c": "Зеркало из тёмного металла с тонким золотым краем"},
    {"text": "Как ты обычно принимаешь важное решение?", "a": "Слушаю состояние и выбираю то, где становится спокойнее", "b": "Сравниваю факты, риски и последствия", "c": "Смотрю на общий рисунок: что повторяется и куда ведёт линия событий"},
    {"text": "Какого ответа ты ждёшь от рун?", "a": "Бережного ориентира", "b": "Честного предупреждения", "c": "Глубокой интерпретации без лишней мистики"},
]

HUMAN_DAILY_OPENINGS = {
    "light": [
        "🌕 <b>{name}, руна дня</b>\nЯ бы сегодня не шла через усилие. Тут больше про спокойный поворот в нужную сторону.",
        "🌕 <b>{name}, руна дня</b>\nПо этой карте день лучше прожить мягче. Не всё нужно решать через напряжение.",
        "🌕 <b>{name}, руна дня</b>\nЗдесь ощущение такое: тебе важно не потерять себя в чужой срочности.",
        "🌕 <b>{name}, руна дня</b>\nСегодня карта говорит не про большой рывок, а про аккуратный выбор.",
        "🌕 <b>{name}, руна дня</b>\nЯ бы начала с простого: где стало тяжело — там и нужно вернуть себе место.",
    ],
    "dark": [
        "🌑 <b>{name}, руна дня</b>\nЗдесь карта довольно трезвая. Она не пугает, но показывает место, где лучше не закрывать глаза.",
        "🌑 <b>{name}, руна дня</b>\nЯ бы читала это прямо: что-то уже требует более честной позиции.",
        "🌑 <b>{name}, руна дня</b>\nСегодня не стоит сглаживать то, что внутри давно царапает.",
        "🌑 <b>{name}, руна дня</b>\nКарта будто ставит вопрос ребром: где ты слишком долго уступаешь?",
        "🌑 <b>{name}, руна дня</b>\nТут не про конфликт. Скорее про ясную границу без лишнего шума.",
    ],
    "premium": [
        "💠 <b>{name}, руна дня</b>\nЯ бы здесь смотрела не на само событие, а на то, почему оно повторяется именно сейчас.",
        "💠 <b>{name}, руна дня</b>\nУ этой карты есть второй слой. Снаружи всё может выглядеть просто, но мотив глубже.",
        "💠 <b>{name}, руна дня</b>\nЗдесь важно не торопиться с выводом. Сначала посмотри, что связывает детали между собой.",
        "💠 <b>{name}, руна дня</b>\nКарта как будто показывает невидимую нить: кто или что снова возвращает тебя к этой теме.",
        "💠 <b>{name}, руна дня</b>\nЯ бы читала это через подтекст. Не все ответы лежат на поверхности.",
    ],
}

HUMAN_DAILY_CLOSINGS = {
    "light": [
        "На сегодня достаточно одного бережного шага. Не бери на себя больше, чем реально можешь удержать.",
        "Сделай то, после чего внутри станет тише. Остальное можно не трогать прямо сейчас.",
        "Не подстраивайся автоматически. Сначала проверь: тебе от этого легче или тяжелее?",
        "Лучшее действие сегодня — убрать лишнее давление и оставить себе пространство для нормального решения.",
        "Если выбор не созрел, не выжимай его из себя. Подготовь почву — это тоже действие.",
    ],
    "dark": [
        "Сегодня лучше не объяснять очевидное слишком долго. Скажи короче и держись выбранной линии.",
        "Если где-то уже нарушена граница, возвращай её спокойно. Без нападения, но твёрдо.",
        "Смотри на поступки. Слова сейчас могут красиво закрывать неудобный факт.",
        "Не бери чужую ответственность на себя. Особенно если тебя к этому мягко подталкивают.",
        "Твоя задача — не победить, а не предать свою позицию.",
    ],
    "premium": [
        "Сегодня полезнее распутать причину, чем быстро реагировать на поверхность.",
        "Спроси себя: что в этой теме возвращается не первый раз? Там и лежит ключ.",
        "Не расширяй ситуацию новыми действиями, пока не понятен её центр.",
        "Запиши вопрос одной фразой. Лишние слова покажут, где ты сама себя уводишь в сторону.",
        "Не спеши закрывать тему. Сначала пойми, какую роль ты в ней продолжаешь играть.",
    ],
}

HUMAN_QUESTION_OPENINGS = {
    "light": [
        "❓ <b>{name}, по твоему вопросу</b>\nОтвет здесь не резкий. Скорее карта показывает, где внутри уже есть тихое понимание.",
        "❓ <b>{name}, одна карта на вопрос</b>\nЯ бы не читала это категорично. Но направление видно.",
        "❓ <b>{name}, коротко по вопросу</b>\nТут важно не то, чего хочется сразу, а что после этого станет легче держать.",
        "❓ <b>{name}, ответ по ситуации</b>\nКарта говорит мягко, но не пусто: прислушайся к первой реакции.",
        "❓ <b>{name}, без давления</b>\nОтвет проявляется через ощущение, а не через спор с собой. Не дави на него.",
    ],
    "dark": [
        "❓ <b>{name}, по твоему вопросу</b>\nКарта здесь довольно сухая. Она скорее показывает факт, чем успокаивает.",
        "❓ <b>{name}, одна карта на вопрос</b>\nЯ бы смотрела на последствия. Именно там ответ становится понятнее.",
        "❓ <b>{name}, коротко по вопросу</b>\nЗдесь важно не оправдать ситуацию, а увидеть, что она уже делает с тобой.",
        "❓ <b>{name}, отвечаю прямо</b>\nКарта подсвечивает место, где ты можешь уступить больше, чем стоит.",
        "❓ <b>{name}, по сути</b>\nЕсли убрать эмоции, остаётся вопрос границы и цены твоего согласия.",
    ],
    "premium": [
        "❓ <b>{name}, по твоему вопросу</b>\nОтвет прячется не в событии, а в мотиве, который за ним стоит.",
        "❓ <b>{name}, одна карта на вопрос</b>\nЯ бы смотрела глубже: что ты на самом деле хочешь подтвердить этим вопросом?",
        "❓ <b>{name}, коротко по вопросу</b>\nКарта показывает не только направление, но и скрытый узел внутри ситуации.",
        "❓ <b>{name}, через подтекст</b>\nНе спеши с формальным «да» или «нет». Есть слой, который меняет смысл.",
        "❓ <b>{name}, через одну карту</b>\nОтвет идёт через повтор: что уже происходило похожим образом?",
    ],
}

HUMAN_QUESTION_CLOSINGS = {
    "light": [
        "Я бы не делала резкий шаг сегодня. Лучше выбрать маленькое действие, после которого станет спокойнее.",
        "Если после этого решения внутри становится ровнее — это хороший знак. Если сжимает, лучше подождать.",
        "Не пытайся убедить себя силой. Ответ должен стать тише, а не громче.",
        "Сейчас достаточно бережно проверить направление, без обещаний и окончательных решений.",
        "Оставь себе пространство. Этот вопрос не любит давления.",
    ],
    "dark": [
        "Я бы не соглашалась только ради спокойствия. Слишком быстрое согласие здесь может обойтись дороже.",
        "Проверь, не пытаются ли сделать твоё сомнение неудобным. Оно здесь не случайное.",
        "Если факт уже понятен, не оборачивай его в красивое объяснение.",
        "Лучше один честный ответ, чем ещё несколько дней внутреннего торга.",
        "Не бери на себя то, что должен решить другой человек.",
    ],
    "premium": [
        "Я бы переформулировала вопрос короче. Так станет видно, о чём он на самом деле.",
        "Посмотри, где эта тема уже повторялась. Ответ связан не с одним эпизодом.",
        "Не цепляйся за внешнюю форму. Здесь важнее мотив и скрытая выгода ситуации.",
        "Если хочется получить разрешение — спроси себя, от кого именно ты его ждёшь.",
        "Ответ будет понятнее, если смотреть не на слова, а на рисунок последних событий.",
    ],
}


def stable_pick(pool: list[str], *parts: object) -> str:
    if not pool:
        return ""
    raw = ":".join(str(p) for p in parts).encode("utf-8")
    index = int(hashlib.sha256(raw).hexdigest()[:8], 16) % len(pool)
    return pool[index]


async def reading_pause(update: Update, context: ContextTypes.DEFAULT_TYPE, seconds: float | None = None) -> None:
    chat = update.effective_chat
    if chat:
        try:
            await context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)
        except TelegramError:
            bot.logger.exception("Failed to send typing action")
    if seconds and seconds > 0:
        await asyncio.sleep(min(seconds, 0.05))


def stable_alt(user_id: int, day: str, rune_key: str) -> bool:
    raw = f"{user_id}:{day}:{rune_key}".encode("utf-8")
    value = int(hashlib.sha256(raw).hexdigest()[:8], 16) / 0xFFFFFFFF
    return value < ALT_RATE


def random_alt() -> bool:
    return random.random() < ALT_RATE


def rune_title(rune: dict, alt: bool) -> str:
    if alt:
        return f"<b>{rune['name']}</b>\n<u>↺ Перевёрнутое значение</u>"
    return f"<b>{rune['name']}</b>\n<u>→ Прямое значение</u>"


def get_user_palette(update: Update) -> str:
    user = update.effective_user
    if not user:
        return "light"
    try:
        profile = bot.get_user_profile(bot.DB_PATH, user.id)
        if profile and profile.get("palette") in {"light", "dark", "premium"}:
            return profile["palette"]
    except bot.DatabaseError:
        bot.logger.exception("Failed to get user palette")
    return "light"


bot.get_user_palette = get_user_palette


def onboarding_keyboard(step: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("A", callback_data=f"onboarding:{step}:light")], [InlineKeyboardButton("B", callback_data=f"onboarding:{step}:dark")], [InlineKeyboardButton("C", callback_data=f"onboarding:{step}:premium")]])


bot.onboarding_keyboard = onboarding_keyboard


def build_onboarding_question(step: int, name: str) -> str:
    q = bot.ONBOARDING_QUESTIONS[step - 1]
    return f"{name}, настроим твою колоду\n\nВопрос {step}/5\n{q['text']}\n\nA — {q['a']}\nB — {q['b']}\nC — {q['c']}"


bot.build_onboarding_question = build_onboarding_question


def onboarding_result_text(palette: str) -> str:
    titles = {"light": "🌕 Светлая колода настроена", "dark": "🌑 Тёмная колода настроена", "premium": "💠 Премиум-колода настроена"}
    descriptions = {"light": "Мягкие трактовки, больше поддержки и спокойного ориентира.", "dark": "Более прямое чтение: границы, риски и честная позиция.", "premium": "Более глубокий разбор: подтекст, повторяющиеся сигналы и скрытая структура вопроса."}
    return f"{titles.get(palette, 'Колода настроена')}\n\n{descriptions.get(palette, '')}\n\nКолоду можно сменить позже в ⚙️ Настройках."


bot.onboarding_result_text = onboarding_result_text


def product_rune_day_full_text(name: str, main: dict, palette: str) -> str:
    day = get_rune_day_text(main["key"])
    palette_icon = {"light": "🌕", "dark": "🌑", "premium": "💠"}.get(palette, "🌕")
    header = f"{palette_icon} <b>{name}, руна дня — {main['name']}</b>"
    if palette == "premium":
        premium_data = bot.rune_text(main, "premium")
        archetype = (premium_data.get("archetype") or "").rstrip(".")
        if archetype:
            header = f"{palette_icon} <b>{name}, руна дня — {main['name']} · {archetype}</b>"
    parts = [header]
    if day.get("background"):
        parts.append(f"<b>На что обратить внимание сегодня</b>\n{day['background']}")
    if day.get("events"):
        parts.append(f"<b>Что может произойти</b>\n{day['events']}")
    if day.get("advice"):
        parts.append(f"<b>Что сделать сегодня</b>\n{day['advice']}")
    if palette == "premium":
        premium_data = bot.rune_text(main, "premium")
        distortion = premium_data.get("distortion", "")
        key_action = premium_data.get("key_action", "")
        if distortion or key_action:
            deep = []
            if distortion:
                deep.append(f"<i>Искажение:</i> {distortion}")
            if key_action:
                deep.append(f"<i>Ключевое действие:</i> {key_action}")
            parts.append("✧ <b>Глубинный слой</b>\n" + "\n".join(deep))
    return "\n\n".join(parts)


def product_daily_text(name: str, main: dict, main_text: dict, aux: dict, aux_text: dict, palette: str, main_alt: bool, aux_alt: bool) -> str:
    key = palette if palette in HUMAN_DAILY_OPENINGS else "light"
    opening = stable_pick(HUMAN_DAILY_OPENINGS[key], name, main["key"], aux["key"], date.today().isoformat()).format(name=name)
    closing = stable_pick(HUMAN_DAILY_CLOSINGS[key], name, main["key"], aux["key"], "closing", date.today().isoformat())
    main_desc = alt_meaning(main, palette) if main_alt else main_text["short_desc"]
    aux_desc = alt_meaning(aux, palette) if aux_alt else aux_text["short_desc"]
    return (
        f"{opening}\n\n"
        f"{rune_title(main, main_alt)}\n\n"
        f"{main_desc}\n\n"
        f"<i>А рядом ложится</i>\n{rune_title(aux, aux_alt)}\n\n"
        f"{aux_desc}\n\n"
        f"{closing}"
    )


def product_question_text(name: str, question: str, rune: dict, answer: str, palette: str, alt: bool) -> str:
    key = palette if palette in HUMAN_QUESTION_OPENINGS else "light"
    opening = stable_pick(HUMAN_QUESTION_OPENINGS[key], name, question, rune["key"], alt).format(name=name)
    closing = stable_pick(HUMAN_QUESTION_CLOSINGS[key], name, question, rune["key"], alt, "closing")
    body = alt_meaning(rune, palette) if alt else answer
    return (
        f"{opening}\n\n"
        f"<i>Твой вопрос:</i> {question}\n\n"
        f"{rune_title(rune, alt)}\n\n"
        f"{body}\n\n"
        f"{closing}"
    )


async def product_start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    if not update.effective_user or not update.effective_message:
        return
    if not bot.is_private(update):
        await update.effective_message.reply_text("Открой личку с ботом. Там появится меню.", reply_markup=bot.private_link_markup(context))
        return
    name = bot.user_name(update)
    try:
        bot.ensure_user(bot.DB_PATH, update.effective_user.id, name)
        profile = bot.get_user_profile(bot.DB_PATH, update.effective_user.id)
        if not profile or not profile.get("palette"):
            bot.start_onboarding(bot.DB_PATH, update.effective_user.id)
            await update.effective_message.reply_text(bot.build_onboarding_question(1, name), reply_markup=bot.onboarding_keyboard(1))
            return
    except bot.DatabaseError:
        bot.logger.exception("Failed to start onboarding")
        await update.effective_message.reply_text("Не получилось настроить профиль. Попробуй позже.", reply_markup=bot.MAIN_KEYBOARD)
        return
    await update.effective_message.reply_text(f"{name}, меню готово.\n\nВыбери действие ниже.", reply_markup=bot.MAIN_KEYBOARD)


async def product_runa_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    if not update.effective_user:
        return
    if not await bot.ensure_profile_ready(update, context):
        return
    await reading_pause(update, context, 0.03)
    today = date.today().isoformat()
    try:
        main_name, aux_name = bot.get_or_create_daily_runes(bot.DB_PATH, update.effective_user.id, today, RUNES)
    except bot.DatabaseError:
        bot.logger.exception("Failed to get daily runes")
        await bot.send_private_or_group(update, context, "Не получилось достать руну дня. Попробуй позже.")
        return
    palette = bot.get_user_palette(update)
    main = get_rune_by_name(main_name)
    aux = get_rune_by_name(aux_name)
    image_path = bot.get_rune_image_path(main, palette)
    if not image_path:
        await bot.send_missing_image_error(update, context, main, palette)
        return
    rune_day_data = get_rune_day_text(main["key"])
    if rune_day_data.get("background"):
        text = product_rune_day_full_text(bot.user_name(update), main, palette)
    else:
        text = product_daily_text(bot.user_name(update), main, bot.rune_text(main, palette), aux, bot.rune_text(aux, palette), palette, stable_alt(update.effective_user.id, today, main["key"]), stable_alt(update.effective_user.id, today, aux["key"]))
    await bot.send_private_or_group(update, context, text, image_path=image_path)


async def product_send_one_rune_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str) -> None:
    if not await bot.ensure_profile_ready(update, context):
        return
    await reading_pause(update, context, 0.03)
    palette = bot.get_user_palette(update)
    rune = random.choice(RUNES)
    image_path = bot.get_rune_image_path(rune, palette)
    if not image_path:
        await bot.send_missing_image_error(update, context, rune, palette)
        return
    text_data = bot.rune_text(rune, palette)
    answer = random.choice([text_data["answer_yes"], text_data["answer_no"]])
    text = product_question_text(bot.user_name(update), question, rune, answer, palette, random_alt())
    await bot.send_private_or_group(update, context, text, image_path=image_path)


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await bot.ensure_profile_ready(update, context):
        return
    palette = bot.get_user_palette(update)
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("🌕 Светлая", callback_data="settings:deck:light")], [InlineKeyboardButton("🌑 Тёмная", callback_data="settings:deck:dark")], [InlineKeyboardButton("💠 Премиум", callback_data="settings:deck:premium")]])
    await bot.send_private_or_group(update, context, f"⚙️ Настройки\n\nТекущая колода: {PALETTE_NAMES.get(palette, 'Светлая')}\n\nМожно сменить её вручную:", image_path=None)
    await update.effective_message.reply_text("Выбери колоду:", reply_markup=markup)


async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user:
        return
    await query.answer()
    parts = query.data.split(":")
    if len(parts) != 3 or parts[0] != "settings" or parts[1] != "deck":
        return
    palette = parts[2]
    try:
        set_user_palette(bot.DB_PATH, update.effective_user.id, palette)
    except bot.DatabaseError:
        await query.edit_message_text("Не получилось сменить колоду. Попробуй позже.")
        return
    await query.edit_message_text(f"Готово. Теперь используется колода: {PALETTE_NAMES.get(palette, palette)}.")
    await context.bot.send_message(chat_id=update.effective_user.id, text="Меню обновлено.", reply_markup=bot.MAIN_KEYBOARD)


async def human_reading_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await bot.ensure_profile_ready(update, context):
        return
    context.user_data["state"] = STATE_WAITING_HUMAN
    await bot.send_private_or_group(update, context, HUMAN_READING_TEXT)


async def handle_human_request(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    user = update.effective_user
    if not user:
        return
    sender = f"@{user.username}" if user.username else user.first_name or str(user.id)
    admin_note = f"🕯 Новый личный расклад\n\nОт: {sender}\nID: {user.id}\n\nВопрос:\n{text}"
    for admin_id in bot.ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=admin_note)
        except TelegramError:
            bot.logger.exception("Failed to notify admin about human reading")
    await bot.send_private_or_group(update, context, "🕯 Вопрос принят.\n\nОтвет подготовит человек. Обычно это занимает 5–10 минут.")


old_text_router = bot.text_router
old_build_template_rasklad = bot.build_template_rasklad
old_build_application = bot.build_application


async def product_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.effective_message.text or "").strip()
    if text == HUMAN_READING_BUTTON:
        await human_reading_command(update, context)
        return
    if text == SETTINGS_BUTTON:
        await settings_command(update, context)
        return
    state = context.user_data.get("state")
    if state == STATE_WAITING_HUMAN:
        context.user_data.pop("state", None)
        await handle_human_request(update, context, text)
        return
    await old_text_router(update, context)


def product_build_template_rasklad(name: str, question: str, runes: list, palette: str) -> str:
    text = old_build_template_rasklad(name, question, runes, palette)
    hidden = []
    for rune in runes:
        if random_alt():
            hidden.append(f"— <b>{rune['name']}:</b> {alt_meaning(rune, palette)}")
    if hidden:
        title = "Скрытый слой" if palette != "premium" else "Глубинный слой"
        text += f"\n\n✧ <b>{title}</b>\n" + "\n".join(hidden)
    return text


def patched_short_help() -> str:
    return (
        "ℹ️ <b>Что я умею</b>\n\n"
        "🌞 /runa — вытяну тебе руну дня\n"
        "❓ /ask <i>вопрос</i> — отвечу одной картой («да / нет / зависит»)\n"
        "🔮 /rasklad <i>вопрос</i> — раскину три карты на ситуацию\n"
        f"{HUMAN_READING_BUTTON} — живой разбор от человека, 100 ₽\n"
        f"{SETTINGS_BUTTON} — сменить колоду\n"
        "🜂 /profile — покажу твою колоду\n\n"
        "Если просто нажмёшь кнопку в меню — попрошу написать вопрос отдельным сообщением."
    )


def patched_build_application():
    app = old_build_application()
    app.add_handler(CallbackQueryHandler(settings_callback, pattern=r"^settings:deck:"))
    return app


bot.start_command = product_start_command
bot.runa_command = product_runa_command
bot.send_one_rune_answer = product_send_one_rune_answer
bot.text_router = product_text_router
bot.build_template_rasklad = product_build_template_rasklad
bot.short_help = patched_short_help
bot.build_application = patched_build_application

if __name__ == "__main__":
    bot.main()
