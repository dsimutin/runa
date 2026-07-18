import asyncio
import hashlib
import random
import re
from datetime import date
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import ContextTypes

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

PRODUCT_MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [["🌞 Руна дня", QUESTION_BUTTON], ["🔮 Расклад", HUMAN_READING_BUTTON], [SETTINGS_BUTTON, "💠 Премиум"], ["ℹ️ Помощь"]],
    resize_keyboard=True,
    is_persistent=False,
)

PRODUCT_ONBOARDING_QUESTIONS = [
    {"text": "Ты входишь в незнакомое пространство. Что считываешь первым?", "a": "Атмосферу, свет, воздух, внутреннее ощущение", "b": "Границы, правила, риски и кто управляет ситуацией"},
    {"text": "Когда внутри нет ясности, что тебе ближе?", "a": "Пауза и мягкое прояснение", "b": "Прямой ответ и действие"},
    {"text": "Какого ответа ты ждёшь от рун?", "a": "Бережного ориентира и поддержки", "b": "Честного предупреждения без прикрас"},
]

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


def build_onboarding_question(step: int, name: str) -> str:
    q = bot.ONBOARDING_QUESTIONS[step - 1]
    total = len(bot.ONBOARDING_QUESTIONS)
    return f"{name}, настроим твою колоду\n\nВопрос {step}/{total}\n{q['text']}\n\nA — {q['a']}\nB — {q['b']}"


def onboarding_result_text(palette: str) -> str:
    titles = {"light": "🌕 Светлая колода настроена", "dark": "🌑 Тёмная колода настроена", "premium": "💠 Премиум-колода активирована"}
    descriptions = {
        "light": "Мягкие трактовки, больше поддержки и спокойного ориентира.",
        "dark": "Более прямое чтение: границы, риски и честная позиция.",
        "premium": "Глубокий разбор, уникальные карты и приоритетный доступ к личным раскладам.",
    }
    return f"{titles.get(palette, 'Колода настроена')}\n\n{descriptions.get(palette, '')}\n\nКолоду можно сменить позже в ⚙️ Настройках."


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
    from rune_decks_approved import get_deck_meaning
    from rune_text_repository import get_daily_text, orientation_label

    try:
        day_text = get_daily_text(rune["key"], palette, orientation)
    except KeyError:
        day_text = bot.rune_text(rune, palette).get("short_desc", "")

    parts = re.split(r"\s*Вопрос дня:\s*", day_text, maxsplit=1, flags=re.IGNORECASE)
    meaning = parts[0].strip()
    reflection = parts[1].strip() if len(parts) > 1 else "Что сегодня особенно важно заметить?"
    try:
        advice = get_deck_meaning(rune["key"], palette, orientation == "rev")["advice"].strip()
    except (KeyError, TypeError):
        advice = "Выбери один небольшой шаг, который поддерживает смысл этой руны."

    position = orientation_label(orientation, rune["key"])

    if streak >= 2:
        streak_word = "день" if streak == 1 else "дня" if 2 <= streak <= 4 else "дней"
        streak_line = f"\n\n🔥 <b>Серия:</b> {streak} {streak_word} подряд"
    else:
        streak_line = ""

    return (
        f"🌞 <b>Руна дня</b>\n"
        f"{escape(name)}\n\n"
        f"ᚱ <b>{escape(str(rune['name']))}</b>\n"
        f"<i>{escape(position)}</i>\n\n"
        f"🔎 <b>Основной смысл</b>\n{escape(meaning)}\n\n"
        f"❔ <b>Вопрос для размышления</b>\n{escape(reflection)}\n\n"
        f"🧭 <b>Ориентир на день</b>\n{escape(advice)}"
        f"{streak_line}"
    )


async def product_runa_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    if not update.effective_user:
        return
    if not await bot.ensure_profile_ready(update, context):
        return
    today = date.today().isoformat()
    try:
        rune_name, orientation = await asyncio.to_thread(
            bot.get_or_create_daily_card, update.effective_user.id, today, RUNES
        )
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
    from rune_collage import build_single_rune_card
    from rune_text_repository import orientation_label
    image_path = await asyncio.to_thread(
        build_single_rune_card,
        image_path,
        palette,
        orientation_label(orientation, main["key"]),
    )
    try:
        from database import get_streak
        streak = await asyncio.to_thread(get_streak, update.effective_user.id)
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
    """Format a one-rune answer with the same hierarchy as other readings."""
    answer_icon = {"Да": "✅", "Нет": "🚫"}.get(sphere_data["answer_label"], "◻️")
    rune_name = escape(str(rune["name"]))
    position_line = f"\n<i>{escape(orientation_text)}</i>" if orientation_text else ""
    return (
        f"❓ <b>Ответ на вопрос</b>\n"
        f"{escape(name)}\n\n"
        f"ᚱ <b>{rune_name}</b>{position_line}\n\n"
        f"<i>«{escape(question)}»</i>\n\n"
        f"🔎 <b>Что показывает руна</b>\n{escape(str(sphere_data['short_desc']))}\n\n"
        f"{answer_icon} <b>Ответ</b>\n{escape(str(sphere_data['answer']))}\n\n"
        f"<i>Это текущая тенденция, а не неизменный исход.</i>"
    )


async def product_send_one_rune_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str) -> None:
    if not await bot.ensure_profile_ready(update, context):
        return
    from question_guard import guarded_question_response
    guarded_response = guarded_question_response(question)
    if guarded_response:
        await bot.send_private_or_group(update, context, guarded_response)
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
    from rune_collage import build_single_rune_card
    image_path = await asyncio.to_thread(
        build_single_rune_card,
        image_path,
        palette,
        orientation_label(orientation, rune["key"]),
    )
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
    parts = query.data.split(":")
    if len(parts) != 3 or parts[0] != "settings" or parts[1] != "deck":
        await query.answer("Эта кнопка устарела.", show_alert=True)
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
    await query.answer()
    try:
        await asyncio.to_thread(set_user_palette, update.effective_user.id, palette)
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


def configure_bot_runtime() -> None:
    """Explicitly install the product behaviour used by the final runtime."""
    bot.DECK_DIRS = {"light": "light", "dark": "dark", "premium": "premium"}
    bot.MAIN_KEYBOARD = PRODUCT_MAIN_KEYBOARD
    bot.ONBOARDING_QUESTIONS = PRODUCT_ONBOARDING_QUESTIONS
    bot.get_user_palette = get_user_palette
    bot.onboarding_keyboard = onboarding_keyboard
    bot.build_onboarding_question = build_onboarding_question
    bot.onboarding_result_text = onboarding_result_text
    bot.start_command = product_start_command
    bot.runa_command = product_runa_command
    bot.send_one_rune_answer = product_send_one_rune_answer
    bot.text_router = product_text_router
    bot.build_template_rasklad = product_build_template_rasklad
    bot.short_help = patched_short_help

if __name__ == "__main__":
    configure_bot_runtime()
    bot.main()
