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
    [["🌞 Руна дня", QUESTION_BUTTON], ["🔮 Расклад", HUMAN_READING_BUTTON], [SETTINGS_BUTTON, "💠 Премиум"], ["ℹ️ Помощь"]],
    resize_keyboard=True,
    is_persistent=True,
)

bot.ONBOARDING_QUESTIONS = [
    {"text": "Ты входишь в незнакомое пространство. Что считываешь первым?", "a": "Атмосферу, свет, воздух, внутреннее ощущение", "b": "Границы, правила, риски и кто управляет ситуацией"},
    {"text": "Когда внутри нет ясности, что тебе ближе?", "a": "Пауза и мягкое прояснение", "b": "Прямой ответ и действие"},
    {"text": "Какого ответа ты ждёшь от рун?", "a": "Бережного ориентира и поддержки", "b": "Честного предупреждения без прикрас"},
]

DAILY_PALETTE_ICON = {"light": "🌕", "dark": "🌑", "premium": "💠"}


def _daily_opening(palette: str, name: str) -> str:
    icon = DAILY_PALETTE_ICON.get(palette, "🌕")
    return f"{icon} <b>{name}, руна дня</b>"

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
        "Если пойдёшь в эту сторону — следующий шаг станет легче. Если нет — вопрос вернётся.",
        "Это направление ведёт к более спокойному варианту. Другое — к тому же месту через круг.",
        "Первый шаг здесь маленький. Но именно он меняет, куда выходит ситуация.",
        "Прямо сейчас тут открывается дверь. Через неделю она может закрыться.",
        "Ближайший исход зависит от того, отпустишь ты это или будешь удерживать.",
    ],
    "dark": [
        "Если возьмёшь позицию сейчас — выйдешь с результатом. Если промедлишь — другие займут поле.",
        "Здесь есть одно окно. Его не нужно долго обдумывать — нужно его заметить.",
        "Исход читается прямо: один путь закрывает вопрос, второй его продлевает.",
        "Если закроешь слабое место сейчас — ситуация выровняется. Если нет — она повторится с большей ценой.",
        "Ставка понятна. Важнее не что решить, а когда.",
    ],
    "premium": [
        "Если паттерн распознаётся — ситуация выходит в новое качество. Если нет — повторится в другой форме.",
        "То, что ты видишь снаружи, — это следствие. Причина разворачивается глубже, и именно там ответ.",
        "Этот вопрос ведёт к развязке только если смотреть не на событие, а на то, что оно удерживает.",
        "Исход здесь не в решении. Он в том, какую роль ты готов отпустить.",
        "Ситуация меняется не когда появляется ответ, а когда меняется вопрос.",
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
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("A", callback_data=f"onboarding:{step}:light")],
        [InlineKeyboardButton("B", callback_data=f"onboarding:{step}:dark")],
    ])


bot.onboarding_keyboard = onboarding_keyboard


def build_onboarding_question(step: int, name: str) -> str:
    q = bot.ONBOARDING_QUESTIONS[step - 1]
    total = len(bot.ONBOARDING_QUESTIONS)
    return f"{name}, настроим твою колоду\n\nВопрос {step}/{total}\n{q['text']}\n\nA — {q['a']}\nB — {q['b']}"


bot.build_onboarding_question = build_onboarding_question


def onboarding_result_text(palette: str) -> str:
    titles = {"light": "🌕 Светлая колода настроена", "dark": "🌑 Тёмная колода настроена", "premium": "💠 Премиум-колода активирована"}
    descriptions = {
        "light": "Мягкие трактовки, больше поддержки и спокойного ориентира.",
        "dark": "Более прямое чтение: границы, риски и честная позиция.",
        "premium": "Глубокий разбор, уникальные карты и приоритетный доступ к личным раскладам.",
    }
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
    opening = _daily_opening(palette, name)
    key = palette if palette in HUMAN_DAILY_CLOSINGS else "light"
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
    # Send typing indicator immediately without waiting
    chat = update.effective_chat
    if chat:
        asyncio.create_task(context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING))
    today = date.today().isoformat()
    try:
        rune_name, orientation = bot.get_or_create_daily_card(bot.DB_PATH, update.effective_user.id, today, RUNES)
    except bot.DatabaseError:
        bot.logger.exception("Failed to get daily rune")
        await bot.send_private_or_group(update, context, "Не получилось достать руну дня. Попробуй позже.")
        return
    palette = bot.get_user_palette(update)
    main = get_rune_by_name(rune_name)
    image_path = bot.get_rune_image_path(main, palette)
    if not image_path:
        await bot.send_missing_image_error(update, context, main, palette)
        return
    # Use the new card-of-day texts (card_of_day_short.txt via rune_text_repository)
    from rune_text_repository import get_daily_text
    try:
        day_text = get_daily_text(main["key"], palette, orientation)
    except KeyError:
        day_text = bot.rune_text(main, palette).get("short_desc", "")
    opening = _daily_opening(palette, bot.user_name(update))
    closing = stable_pick(HUMAN_DAILY_CLOSINGS.get(palette, HUMAN_DAILY_CLOSINGS["light"]), bot.user_name(update), main["key"], orientation, "closing", today)
    try:
        from lunar_calendar import moon_phase_today
        moon = moon_phase_today()
        moon_line = f"\n\n{moon['emoji']} {moon['phase_name']} — {moon['description']}"
    except Exception:
        moon_line = ""
    try:
        from database import get_streak
        streak = get_streak(bot.DB_PATH, update.effective_user.id)
        if streak >= 2:
            streak_word = "день" if streak == 1 else "дня" if 2 <= streak <= 4 else "дней"
            streak_line = f"\n\n🔥 {streak} {streak_word} подряд"
        else:
            streak_line = ""
    except Exception:
        streak_line = ""
    text = f"{opening}\n\n{day_text}\n\n{closing}{moon_line}{streak_line}"
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
    # Use new sphere-based да/нет texts (runes_spheres_all.txt via rune_text_repository)
    from rune_text_repository import detect_question_sphere, get_sphere_answer
    from bot import format_one_rune_answer
    sphere = detect_question_sphere(question)
    answer_kind = "yes" if random.random() < 0.5 else "no"
    try:
        sphere_data = get_sphere_answer(rune["key"], palette, sphere, answer_kind)
    except KeyError:
        bot.logger.exception("Sphere answer not found, falling back")
        text_data = bot.rune_text(rune, palette)
        answer = text_data.get("answer_yes" if answer_kind == "yes" else "answer_no", "")
        sphere_data = {
            "short_desc": text_data.get("short_desc", ""),
            "answer": answer,
            "sphere_label": "Принятие решений",
            "answer_label": "Да" if answer_kind == "yes" else "Нет",
        }
    text = format_one_rune_answer(bot.user_name(update), question, rune, sphere_data)
    await bot.send_private_or_group(update, context, text, image_path=image_path)
    try:
        from database import save_spread
        save_spread(bot.DB_PATH, update.effective_user.id, "yes_no", question, rune["name"])
    except Exception:
        bot.logger.exception("Failed to save yes/no spread to history")


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await bot.ensure_profile_ready(update, context):
        return
    palette = bot.get_user_palette(update)
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌕 Светлая", callback_data="settings:deck:light")],
        [InlineKeyboardButton("🌑 Тёмная", callback_data="settings:deck:dark")],
        [InlineKeyboardButton("💠 Премиум — только по подписке", callback_data="settings:deck:premium")],
    ])
    await bot.send_private_or_group(update, context, f"⚙️ Настройки\n\nТекущая колода: {PALETTE_NAMES.get(palette, 'Светлая')}\n\nСветлая и тёмная доступны всем. Премиум — только с активной подпиской.", image_path=None)
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
    if palette == "premium":
        from premium_subscription import is_premium_active
        if not is_premium_active(bot.DB_PATH, update.effective_user.id):
            await query.answer("Премиум-колода доступна только по подписке 💠", show_alert=True)
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text="💠 Премиум-колода доступна только с активной подпиской.\n\nНажми 💠 Премиум в меню, чтобы оформить.",
                reply_markup=bot.MAIN_KEYBOARD,
            )
            return
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
        "❓ /ask <i>вопрос</i> — отвечу одной картой (да / нет)\n"
        "🔮 /rasklad <i>вопрос</i> — раскину три карты на ситуацию\n"
        f"{HUMAN_READING_BUTTON} — живой разбор от человека, 100 ₽\n"
        f"{SETTINGS_BUTTON} — сменить колоду\n"
        "✦ /profile — покажу твою колоду\n\n"
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
