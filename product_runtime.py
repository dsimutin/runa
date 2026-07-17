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

HUMAN_DAILY_OPENINGS = {
    "light": [
        "{icon} <b>{name}, руна дня</b>",
        "{icon} <b>{name}, вот что сегодня рядом</b>",
        "{icon} <b>{name}, на сегодня выпало это</b>",
        "{icon} <b>{name}, тихий ориентир на день</b>",
        "{icon} <b>{name}, сегодняшний знак</b>",
    ],
    "dark": [
        "{icon} <b>{name}, руна дня</b>",
        "{icon} <b>{name}, вот прямой сигнал на сегодня</b>",
        "{icon} <b>{name}, сегодня расклад такой</b>",
        "{icon} <b>{name}, факт дня</b>",
        "{icon} <b>{name}, на сегодня — это</b>",
    ],
    "premium": [
        "{icon} <b>{name}, руна дня</b>",
        "{icon} <b>{name}, сегодняшний слой</b>",
        "{icon} <b>{name}, вот что сегодня на поверхности</b>",
        "{icon} <b>{name}, отправная точка дня</b>",
        "{icon} <b>{name}, сегодняшний узел</b>",
    ],
}


def _daily_opening(palette: str, name: str, seed_parts: tuple = ()) -> str:
    icon = DAILY_PALETTE_ICON.get(palette, "🌕")
    pool = HUMAN_DAILY_OPENINGS.get(palette, HUMAN_DAILY_OPENINGS["light"])
    template = stable_pick(pool, name, *seed_parts) if seed_parts else pool[0]
    return template.format(icon=icon, name=name)

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


def get_user_palette(update: Update) -> str:
    user = update.effective_user
    if not user:
        return "light"
    try:
        profile = bot.get_user_profile(user.id)
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


def rune_info_keyboard(rune_pairs: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """Build the traditional rune reference keyboard.

    rune_pairs: list of (rune_key, rune_display_name), up to 3 per row.
    """
    buttons = [
        InlineKeyboardButton(name, callback_data=f"rune_info:{key}")
        for key, name in rune_pairs
    ]
    rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    return InlineKeyboardMarkup(rows)


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


async def product_start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    if not update.effective_user or not update.effective_message:
        return
    if not bot.is_private(update):
        await update.effective_message.reply_text("Открой личку с ботом. Там появится меню.", reply_markup=bot.private_link_markup(context))
        return
    name = bot.user_name(update)
    try:
        bot.ensure_user(update.effective_user.id, name)
        profile = bot.get_user_profile(update.effective_user.id)
        if not profile or not profile.get("palette"):
            bot.start_onboarding(update.effective_user.id)
            await update.effective_message.reply_text(bot.build_onboarding_question(1, name), reply_markup=bot.onboarding_keyboard(1))
            return
    except bot.DatabaseError:
        bot.logger.exception("Failed to start onboarding")
        await update.effective_message.reply_text("Не получилось настроить профиль. Попробуй позже.", reply_markup=bot.main_keyboard_for(update.effective_user.id))
        return
    await update.effective_message.reply_text(f"{name}, меню готово.\n\nВыбери действие ниже.", reply_markup=bot.main_keyboard_for(update.effective_user.id))


def build_daily_card_text(
    name: str,
    palette: str,
    rune: dict,
    orientation: str,
    day: str,
    streak: int = 0,
) -> str:
    """Single source of truth for the daily-card message text.

    Used by both the on-demand '🌞 Руна дня' button (product_runa_command)
    and the 09:00 broadcast (daily_broadcast.send_daily_rune) so the two
    can never drift into different formats again.
    """
    from rune_text_repository import get_daily_text

    try:
        day_text = get_daily_text(rune["key"], palette, orientation)
    except KeyError:
        day_text = bot.rune_text(rune, palette).get("short_desc", "")

    opening = _daily_opening(palette, name, (rune["key"], orientation, day))
    closing = stable_pick(
        HUMAN_DAILY_CLOSINGS.get(palette, HUMAN_DAILY_CLOSINGS["light"]),
        name, rune["key"], orientation, "closing", day,
    )

    if streak >= 2:
        streak_word = "день" if streak == 1 else "дня" if 2 <= streak <= 4 else "дней"
        streak_line = f"\n\n🔥 {streak} {streak_word} подряд"
    else:
        streak_line = ""

    return f"{opening}\n\n{day_text}\n\n{closing}{streak_line}"


async def product_runa_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    if not update.effective_user:
        return
    if not await bot.ensure_profile_ready(update, context):
        return
    today = date.today().isoformat()
    try:
        rune_name, orientation = bot.get_or_create_daily_card(update.effective_user.id, today, RUNES)
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
    try:
        from database import get_streak
        streak = get_streak(update.effective_user.id)
    except Exception:
        streak = 0
    text = build_daily_card_text(bot.user_name(update), palette, main, orientation, today, streak)
    await bot.send_private_or_group(update, context, text, image_path=image_path, reading_mode=True)


def product_yes_no_text(
    name: str,
    question: str,
    rune: dict,
    orientation_text: str,
    sphere_data: dict,
) -> str:
    """Format the yes/no one-rune answer using the opening/closing phrase
    pools that already existed in this file but were never wired in.

    The verdict (✅/🚫 + text starting with an unambiguous Да/Нет variant,
    see _vary_verdict_opener) stays on its own line and is never replaced
    or softened by the opening/closing framing — those only add context
    before and after the actual answer.
    """
    palette_key = sphere_data.get("palette", "light")
    key = palette_key if palette_key in HUMAN_QUESTION_OPENINGS else "light"
    opening = random.choice(HUMAN_QUESTION_OPENINGS[key]).format(name=name)
    closing = random.choice(HUMAN_QUESTION_CLOSINGS[key])
    answer_icon = {"Да": "✅", "Нет": "🚫"}.get(sphere_data["answer_label"], "◻️")
    rune_line = f"{rune['name']} · {orientation_text}" if orientation_text else rune["name"]
    return (
        f"{opening}\n\n"
        f"<i>Твой вопрос:</i> {question}\n\n"
        f"<b>Сфера вопроса:</b> {sphere_data['sphere_label']}\n\n"
        f"{rune_line}\n\n"
        f"{sphere_data['short_desc']}\n\n"
        f"{answer_icon} {sphere_data['answer']}\n\n"
        f"{closing}"
    )


async def product_send_one_rune_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str) -> None:
    if not await bot.ensure_profile_ready(update, context):
        return
    await reading_pause(update, context, 0.03)
    palette = bot.get_user_palette(update)
    from rune_text_repository import draw_yes_no_rune, yes_no_draw
    rune = draw_yes_no_rune(RUNES)
    # Reversible cards use their orientation for polarity. Symmetric cards
    # stay visually upright and draw polarity independently.
    orientation, answer_kind = yes_no_draw(rune["key"])
    image_path = bot.get_rune_image_path(rune, palette)
    if not image_path:
        await bot.send_missing_image_error(update, context, rune, palette)
        return
    from rune_text_repository import detect_question_sphere, get_sphere_answer, orientation_label
    sphere = detect_question_sphere(question)
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
    sphere_data["palette"] = palette
    text = product_yes_no_text(
        bot.user_name(update), question, rune, orientation_label(orientation, rune["key"]), sphere_data
    )
    await bot.send_private_or_group(update, context, text, image_path=image_path, reading_mode=True)
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


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await bot.ensure_profile_ready(update, context):
        return
    palette = bot.get_user_palette(update)
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌕 Светлая", callback_data="settings:deck:light")],
        [InlineKeyboardButton("🌑 Тёмная", callback_data="settings:deck:dark")],
        [InlineKeyboardButton("💠 Премиум — только по подписке", callback_data="settings:deck:premium")],
    ])
    await bot.send_private_or_group(
        update,
        context,
        "⚙️ Настройки\n\n"
        f"Текущая колода: {PALETTE_NAMES.get(palette, 'Светлая')}\n\n"
        "Светлая и тёмная доступны всем. Премиум — только с активной подпиской.",
        image_path=None,
    )
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
        if not is_premium_active(update.effective_user.id):
            await query.answer("Премиум-колода доступна только по подписке 💠", show_alert=True)
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text="💠 Премиум-колода доступна только с активной подпиской.\n\nНажми 💠 Премиум в меню, чтобы оформить.",
                reply_markup=bot.main_keyboard_for(update.effective_user.id),
            )
            return
    try:
        set_user_palette(update.effective_user.id, palette)
    except bot.DatabaseError:
        await query.edit_message_text("Не получилось сменить колоду. Попробуй позже.")
        return
    await query.edit_message_text(f"Готово. Теперь используется колода: {PALETTE_NAMES.get(palette, palette)}.")
    await context.bot.send_message(chat_id=update.effective_user.id, text="Меню обновлено.", reply_markup=bot.main_keyboard_for(update.effective_user.id))


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
