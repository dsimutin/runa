import asyncio
import logging
import os
import random
from datetime import date
from typing import Any, Dict, List

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from database import (
    DatabaseError,
    ensure_user,
    get_or_create_daily_card,
    get_user_profile,
    init_db,
    save_onboarding_answer,
    start_onboarding,
)
from rasklad_engine import generate_rasklad
from rune_text_repository import (
    draw_distinct_runes_with_orientations,
    get_daily_text,
    orientation_label,
)
from runes_data import RUNES, get_rune_by_name

try:
    from runes_interpretations import PSYCHOTYPES, get_interpretation
except Exception:
    PSYCHOTYPES = {}
    get_interpretation = None

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DB_PATH = os.getenv("DB_PATH", "rune_bot.db")
PORT = int(os.getenv("PORT", "10000"))
WEBHOOK_URL = (os.getenv("WEBHOOK_URL") or os.getenv("RENDER_EXTERNAL_URL", "")).strip().rstrip("/")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "webhook").strip().strip("/") or "webhook"
IS_CLOUD_RUN = bool(os.getenv("K_SERVICE"))


def parse_admin_ids(raw_value: str) -> set[int]:
    ids: set[int] = set()
    for raw_id in raw_value.split(","):
        value = raw_id.strip()
        if not value:
            continue
        try:
            ids.add(int(value))
        except ValueError:
            logging.getLogger(__name__).warning("Invalid ADMIN_IDS value ignored: %r", value)
    return ids


ADMIN_IDS = parse_admin_ids(os.getenv("ADMIN_IDS", ""))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DECK_DIRS = {"light": "light", "dark": "dark", "premium": "premium"}
MAX_PHOTO_CAPTION_LENGTH = 1000

STATE_WAITING_ASK = "waiting_ask"
STATE_WAITING_RASKLAD = "waiting_rasklad"

PALETTE_LABELS = {
    "light": "светлая",
    "dark": "тёмная",
    "premium": "премиум",
}

DEFAULT_PSYCHOTYPES = {
    "light": {
        "key": "intuitive_integrator",
        "name": "Интуитивный интегратор",
        "description": "светлая палитра — мягкая, тёплая, интуитивная",
        "reading_style": "восстановление, смысл и внутреннюю ясность",
    },
    "dark": {
        "key": "will_strategist",
        "name": "Волевой стратег",
        "description": "тёмная палитра — глубокая, контрастная, собранная",
        "reading_style": "структуру, силу и прямой знак",
    },
    "premium": {
        "key": "premium_seeker",
        "name": "Премиум-проводник",
        "description": "премиум палитра — глубинная, архетипичная, личная",
        "reading_style": "скрытый мотив, внутреннюю трансформацию и точное действие",
    },
}

ONBOARDING_QUESTIONS = [
    {
        "text": "Ты заходишь в незнакомое место. Что замечаешь первым?",
        "a": "Атмосферу: свет, воздух, настроение, людей",
        "b": "Структуру: входы, выходы, правила, кто контролирует пространство",
        "c": "Скрытый смысл: зачем это место появилось на твоём пути",
    },
    {
        "text": "Когда внутри тревожно, что помогает быстрее?",
        "a": "Побыть в тишине, собрать ощущения, мягко вернуть себя в баланс",
        "b": "Назвать проблему прямо, принять решение и начать действовать",
        "c": "Посмотреть глубже: какой повторяющийся сценарий сейчас включился",
    },
    {
        "text": "Какой символ тебе ближе прямо сейчас?",
        "a": "Тёплый луч на закрытой двери",
        "b": "Золотой ключ в тёмной комнате",
        "c": "Пустое пространство, где рождается новый смысл",
    },
]

logging.basicConfig(format="%(asctime)s | %(name)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [["🌞 Руна дня", "❓ Да / Нет"], ["🔮 Расклад", "ℹ️ Помощь"]],
    resize_keyboard=True,
)
MAIN_KEYBOARD_FACTORY = None


def main_keyboard_for(user_id: int) -> ReplyKeyboardMarkup:
    """Return the current product keyboard for the message recipient."""
    if callable(MAIN_KEYBOARD_FACTORY):
        return MAIN_KEYBOARD_FACTORY(user_id)
    return MAIN_KEYBOARD

# Shown after a rune reading so the phone keyboard doesn't pop up (ReplyKeyboardRemove triggers it)
READING_KEYBOARD = ReplyKeyboardMarkup([["↩ Меню"]], resize_keyboard=True)


def strip_html(text: str) -> str:
    return (
        text.replace("<b>", "").replace("</b>", "")
        .replace("<u>", "").replace("</u>", "")
        .replace("<i>", "").replace("</i>", "")
    )


def wants_html(text: str) -> bool:
    return any(tag in text for tag in ("<b>", "</b>", "<u>", "</u>", "<i>", "</i>"))


def is_private(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.type == "private")


def is_admin(update: Update) -> bool:
    user = update.effective_user
    return bool(user and user.id in ADMIN_IDS)


async def post_init(application: Application) -> None:
    me = await application.bot.get_me()
    application.bot_data["bot_username"] = me.username
    logger.info("Telegram bot connected: id=%s username=@%s name=%s", me.id, me.username, me.first_name)


def user_name(update: Update) -> str:
    user = update.effective_user
    if not user:
        return "друг"
    return user.first_name or user.username or "друг"


def log_update(update: Update, action: str) -> None:
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message
    logger.info(
        "%s | user_id=%s username=%s chat_id=%s chat_type=%s text=%r",
        action,
        user.id if user else None,
        user.username if user else None,
        chat.id if chat else None,
        chat.type if chat else None,
        message.text if message else None,
    )


def bot_link(context: ContextTypes.DEFAULT_TYPE) -> str:
    username = context.application.bot_data.get("bot_username") or "runes2026_bot"
    return f"https://t.me/{username}"


def private_link_markup(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Открыть личку с ботом", url=bot_link(context))]])


def onboarding_keyboard(step: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("A", callback_data=f"onboarding:{step}:light")],
            [InlineKeyboardButton("B", callback_data=f"onboarding:{step}:dark")],
            [InlineKeyboardButton("C", callback_data=f"onboarding:{step}:premium")],
        ]
    )


def build_onboarding_question(step: int, name: str) -> str:
    question = ONBOARDING_QUESTIONS[step - 1]
    return (
        f"✦ {name}, выбери вариант\n\n"
        f"Вопрос {step}/3\n{question['text']}\n\n"
        f"A — {question['a']}\n"
        f"B — {question['b']}\n"
        f"C — {question['c']}"
    )


def psychotype_for(palette: str) -> Dict[str, str]:
    return (PSYCHOTYPES or {}).get(palette) or DEFAULT_PSYCHOTYPES[palette]


def onboarding_result_text(palette: str) -> str:
    profile = psychotype_for(palette)
    return (
        "✦ Колода закреплена\n\n"
        f"Твоя палитра: {profile['description']}.\n\n"
        f"Стиль чтения: {profile['reading_style']}.\n\n"
        "Теперь можно выбрать действие ниже."
    )


def get_user_palette(update: Update) -> str:
    user = update.effective_user
    if not user:
        return "light"
    try:
        profile = get_user_profile(user.id)
        if profile and profile.get("palette") in {"light", "dark", "premium"}:
            return profile["palette"]
    except DatabaseError:
        logger.exception("Failed to get user palette")
    return "light"


def rune_text(rune: Dict[str, Any], palette: str) -> Dict[str, Any]:
    """Compatibility shim used by product_runtime.py."""
    if get_interpretation:
        return get_interpretation(rune.get("key", ""), palette, rune)
    return {}


def build_template_rasklad(name: str, question: str, runes: List[Dict[str, Any]], palette: str) -> str:
    """Compatibility shim used by product_runtime.py."""
    from rasklad_engine import generate_rasklad as _gen
    rune_draws = [(r, "up") for r in runes]
    return _gen(rune_draws, question, palette, name)


def get_rune_image_path(rune: Dict[str, Any], palette: str) -> str | None:
    palette_images = rune.get("palette_image_files")
    if palette_images:
        image_file = palette_images.get(palette) or palette_images.get("light")
        deck_dir = DECK_DIRS.get(palette, "light")
        candidates = [
            os.path.join(BASE_DIR, deck_dir, image_file),
            os.path.join(BASE_DIR, "decks", deck_dir, image_file),
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return None

    image_file = rune.get("image_file")
    if not image_file:
        return None

    deck_dir = DECK_DIRS.get(palette, "light")
    candidates = [
        os.path.join(BASE_DIR, deck_dir, image_file),
        os.path.join(BASE_DIR, "decks", deck_dir, image_file),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path

    logger.warning("Rune image not found: palette=%s file=%s", palette, image_file)
    return None


def check_deck_files() -> Dict[str, List[str]]:
    missing: Dict[str, List[str]] = {}
    for palette in ("light", "dark", "premium"):
        missing[palette] = []
        for rune in RUNES:
            if not get_rune_image_path(rune, palette):
                missing[palette].append(rune.get("image_file", rune.get("name", "unknown")))
    return missing


def format_daily_message(name: str, rune: Dict[str, Any], palette: str, orientation: str, text: str) -> str:
    return (
        f"🌞 <b>{name}, карта дня</b>\n\n"
        f"<b>Карта:</b> {rune['name']}\n"
        f"<b>Положение:</b> {orientation_label(orientation, rune['key'])}\n"
        f"<b>Колода:</b> {PALETTE_LABELS.get(palette, palette)}\n\n"
        f"{text}"
    )


def format_one_rune_answer(
    name: str,
    question: str,
    rune: Dict[str, Any],
    text_data: Dict[str, str],
    orientation_text: str = "",
) -> str:
    answer_icon = "✅" if text_data['answer_label'] == "Да" else "🚫"
    rune_line = f"{rune['name']} · {orientation_text}" if orientation_text else rune['name']
    return (
        f"❓ <b>Вопрос:</b> <i>{question}</i>\n\n"
        f"{rune_line}\n\n"
        f"{text_data['short_desc']}\n\n"
        f"{answer_icon} {text_data['answer']}"
    )


async def ensure_profile_ready(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    message = update.effective_message
    if not user or not message:
        return False
    if not is_private(update):
        return True
    try:
        ensure_user(user.id, user_name(update))
        profile = get_user_profile(user.id)
        if profile and profile.get("palette"):
            return True
        step = profile.get("onboarding_step", 0) if profile else 0
        if step <= 0:
            start_onboarding(user.id)
            step = 1
        await message.reply_text(build_onboarding_question(step, user_name(update)), reply_markup=onboarding_keyboard(step))
        return False
    except DatabaseError:
        logger.exception("Failed to prepare user profile")
        await message.reply_text("Что-то пошло не так. Попробуй ещё раз через минуту.")
        return False


async def _send_text_message(message, text: str, reply_markup=None, parse_mode: str | None = None) -> None:
    await message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)


async def _send_bot_text(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, parse_mode: str | None = None) -> None:
    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)


async def send_private_or_group(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    *,
    image_path: str | None = None,
    reading_mode: bool = False,
    show_shuffle: bool = True,
) -> None:
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    parse_mode = "HTML" if wants_html(text) else None
    plain_text = strip_html(text)
    reply_markup = READING_KEYBOARD if reading_mode else main_keyboard_for(user.id)

    async def show_shuffle(send_message) -> None:
        """Brief anticipation without replacing or re-sending the final card."""
        frames = (
            "🔮 ᚠ · ᚱ · ᚨ  Перемешиваю руны…",
            "🔮 ᚱ · ᚨ · ᚠ  Слушаю вопрос…",
            "🔮 ᚨ · ᚠ · ᚱ  Руна выбрана",
        )
        loading = None
        try:
            loading = await send_message(text=frames[0])
            for frame in frames[1:]:
                await asyncio.sleep(0.32)
                await loading.edit_text(frame)
            await asyncio.sleep(0.28)
        except TelegramError:
            logger.debug("Rune shuffle animation unavailable", exc_info=True)
        finally:
            if loading:
                try:
                    await loading.delete()
                except TelegramError:
                    pass

    async def private_shuffle() -> None:
        async def send_message(**kwargs):
            return await message.reply_text(**kwargs)
        await show_shuffle(send_message)

    async def group_private_shuffle() -> None:
        async def send_message(**kwargs):
            return await context.bot.send_message(chat_id=user.id, **kwargs)
        await show_shuffle(send_message)

    async def send_to_private(target_text: str, mode: str | None) -> None:
        if image_path:
            if reading_mode and show_shuffle:
                await private_shuffle()
            with open(image_path, "rb") as image_file:
                if len(target_text) <= MAX_PHOTO_CAPTION_LENGTH:
                    await message.reply_photo(photo=image_file, caption=target_text, reply_markup=reply_markup, parse_mode=mode)
                else:
                    await message.reply_photo(photo=image_file)
                    await _send_text_message(message, target_text, reply_markup=reply_markup, parse_mode=mode)
        else:
            await _send_text_message(message, target_text, reply_markup=reply_markup, parse_mode=mode)

    async def send_to_group_private(target_text: str, mode: str | None) -> None:
        if image_path:
            if reading_mode and show_shuffle:
                await group_private_shuffle()
            with open(image_path, "rb") as image_file:
                if len(target_text) <= MAX_PHOTO_CAPTION_LENGTH:
                    await context.bot.send_photo(chat_id=user.id, photo=image_file, caption=target_text, parse_mode=mode)
                else:
                    await context.bot.send_photo(chat_id=user.id, photo=image_file)
                    await _send_bot_text(context, user.id, target_text, parse_mode=mode)
        else:
            await _send_bot_text(context, user.id, target_text, parse_mode=mode)
        await message.reply_text("Отправил ответ тебе в личку ✨")

    try:
        if is_private(update):
            await send_to_private(text, parse_mode)
        else:
            await send_to_group_private(text, parse_mode)
    except BadRequest:
        logger.exception("HTML send failed; retrying plain text")
        try:
            if is_private(update):
                await send_to_private(plain_text, None)
            else:
                await send_to_group_private(plain_text, None)
        except TelegramError:
            logger.exception("Plain fallback failed")
            await message.reply_text("Сообщение не ушло. Давай попробуем ещё раз через минуту.")
    except Forbidden:
        await message.reply_text(
            "Чтобы я мог писать тебе лично, открой со мной личный чат и нажми /start.",
            reply_markup=private_link_markup(context),
        )
    except (OSError, TelegramError):
        logger.exception("Failed to send response")
        await message.reply_text("Сообщение не ушло. Давай попробуем ещё раз через минуту.")


def short_help() -> str:
    return (
        "ℹ️ <b>Как пользоваться ботом</b>\n\n"
        "🌞 <b>Руна дня</b> — одна карта с фокусом на сегодня\n"
        "❓ <b>Вопрос (да/нет)</b> — одна руна, короткий ответ по ситуации\n"
        "🔮 <b>Расклад</b> — три карты: прошлое / настоящее / будущее\n"
        "📜 <b>Значения рун</b> — отдельный справочник по традиционной символике\n"
        "🕯 <b>Личный расклад</b> — живой ответ человека на твой вопрос\n"
        "💠 <b>Премиум</b> — уникальная колода и 3 бесплатных личных расклада в месяц\n\n"
        "<b>Дополнительные команды:</b>\n"
        "/pair <i>имя</i> — расклад на двоих (ты + партнёр)\n"
        "/history — последние 7 дней твоих рун и серия дней\n"
        "/premium — статус подписки или оформить\n"
        "/profile — твоя колода и стиль чтения\n"
        "/subscribe — включить ежедневную рассылку\n"
        "/unsubscribe — выключить рассылку\n"
        "/weekday — выбрать день для руны недели (премиум)"
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /start")
    context.user_data.clear()
    name = user_name(update)

    if not is_private(update):
        await update.effective_message.reply_text(
            "Раскладам нужна личка. Открой со мной личный чат и нажми /start — там и продолжим.",
            reply_markup=private_link_markup(context),
        )
        return

    try:
        ensure_user(update.effective_user.id, name)
        profile = get_user_profile(update.effective_user.id)
        if not profile or not profile.get("palette"):
            start_onboarding(update.effective_user.id)
            await update.effective_message.reply_text(build_onboarding_question(1, name), reply_markup=onboarding_keyboard(1))
            return
    except DatabaseError:
        logger.exception("Failed to start onboarding")
        await update.effective_message.reply_text("Что-то пошло не так. Попробуй ещё раз через минуту.")
        return

    await update.effective_message.reply_text(f"✦ {name}, твоя колода уже выбрана.\n\nС чего начнём?", reply_markup=main_keyboard_for(update.effective_user.id))


async def onboarding_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user:
        return

    await query.answer()
    try:
        _, step_raw, answer = query.data.split(":", 2)
        int(step_raw)
    except (ValueError, AttributeError):
        await query.edit_message_text("Не удалось прочитать ответ. Нажми /start и попробуй снова.")
        return

    try:
        result = save_onboarding_answer(update.effective_user.id, answer, len(ONBOARDING_QUESTIONS))
    except DatabaseError:
        logger.exception("Failed to save onboarding answer")
        await query.edit_message_text("Не получилось сохранить ответ. Попробуй позже.")
        return

    if result.get("completed"):
        await query.edit_message_text(onboarding_result_text(result["palette"]))
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text=(
                "👇 Что можно сделать:\n\n"
                "🌞 Руна дня — карта и положение на сегодня\n"
                "❓ Да / Нет — быстрый ответ одной картой\n"
                "🔮 Расклад — прошлое / настоящее / будущее\n\n"
                "Выбери действие ниже"
            ),
            reply_markup=main_keyboard_for(update.effective_user.id),
        )
        return

    next_step = result["next_step"]
    await query.edit_message_text(build_onboarding_question(next_step, user_name(update)), reply_markup=onboarding_keyboard(next_step))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /help")
    context.user_data.clear()
    if not await ensure_profile_ready(update, context):
        return
    await send_private_or_group(update, context, short_help())


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /profile")
    if not await ensure_profile_ready(update, context):
        return

    palette = get_user_palette(update)
    profile = psychotype_for(palette)
    text = (
        "👤 Профиль\n\n"
        f"Колода: {PALETTE_LABELS.get(palette, palette)}\n"
        f"Стиль: {profile['name']}\n\n"
        f"Как читается:\n{profile['reading_style']}.\n\n"
        "Сменить колоду: ⚙️ Настройки в меню.\n"
        "Сброс профиля: удали чат с ботом и начни заново."
    )
    await send_private_or_group(update, context, text)


async def check_decks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /check_decks")
    if not is_admin(update):
        await update.effective_message.reply_text("Эта техническая команда доступна только администратору.")
        return

    missing = check_deck_files()
    lines = ["🧩 Проверка колод", ""]
    for palette in ("light", "dark", "premium"):
        count = len(RUNES) - len(missing[palette])
        lines.append(f"{PALETTE_LABELS.get(palette, palette)}: {count}/{len(RUNES)}")
        if missing[palette]:
            lines.append("Не найдены:")
            lines.extend(f"— {name}" for name in missing[palette])
        lines.append("")
    await send_private_or_group(update, context, "\n".join(lines).strip())


async def send_missing_image_error(update: Update, context: ContextTypes.DEFAULT_TYPE, rune: Dict[str, Any], palette: str) -> None:
    await send_private_or_group(
        update,
        context,
        f"Не найдена карта {rune.get('image_file', rune.get('name', ''))} в папке {palette}. Проверь /check_decks.",
    )


async def runa_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /runa")
    context.user_data.clear()
    if not update.effective_user:
        return
    if not await ensure_profile_ready(update, context):
        return

    today = date.today().isoformat()
    try:
        rune_name, orientation = get_or_create_daily_card(update.effective_user.id, today, RUNES)
    except DatabaseError:
        logger.exception("Failed to get daily card")
        await send_private_or_group(update, context, "Сейчас не получается достать карту дня. Попробуй чуть позже.")
        return

    palette = get_user_palette(update)
    rune = get_rune_by_name(rune_name)
    image_path = get_rune_image_path(rune, palette)
    if not image_path:
        await send_missing_image_error(update, context, rune, palette)
        return

    try:
        text_value = get_daily_text(rune["key"], palette, orientation)
    except KeyError:
        logger.exception("Daily text not found")
        await send_private_or_group(update, context, "Для этой карты не найден текст карты дня в загруженном файле.")
        return

    text = format_daily_message(user_name(update), rune, palette, orientation, text_value)
    await send_private_or_group(update, context, text, image_path=image_path, reading_mode=True)


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /ask")
    if not await ensure_profile_ready(update, context):
        return

    question = " ".join(context.args).strip()
    if not question:
        context.user_data["state"] = STATE_WAITING_ASK
        await update.effective_message.reply_text("❓ Напиши вопрос — отвечу Да / Нет одной картой.", reply_markup=main_keyboard_for(update.effective_user.id) if is_private(update) else None)
        return

    from product_runtime import product_send_one_rune_answer
    await product_send_one_rune_answer(update, context, question)


async def rasklad_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /rasklad")
    if not await ensure_profile_ready(update, context):
        return

    question = " ".join(context.args).strip()
    if not question:
        context.user_data["state"] = STATE_WAITING_RASKLAD
        await update.effective_message.reply_text("🔮 Напиши вопрос — раскину три карты: прошлое / настоящее / будущее.", reply_markup=main_keyboard_for(update.effective_user.id) if is_private(update) else None)
        return

    await send_rasklad(update, context, question)


def choose_distinct_runes(count: int = 3) -> List[Dict[str, Any]]:
    """Return `count` distinct rune dicts, no orientation attached.

    Kept for compatibility with send_approved_rasklad's original signature;
    the live send_rasklad path below uses draw_distinct_runes_with_orientations
    instead, since orientation is used (upright/reversed genuinely changes
    the reading and is shown on each card).
    """
    return random.sample(RUNES, min(count, len(RUNES)))


async def send_rasklad(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str) -> None:
    if not await ensure_profile_ready(update, context):
        return

    if update.effective_chat:
        try:
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        except TelegramError:
            pass

    name = user_name(update)
    palette = get_user_palette(update)
    rune_draws = draw_distinct_runes_with_orientations(RUNES, 3)
    image_paths = [get_rune_image_path(rune, palette) for rune, _ in rune_draws]
    if not all(image_paths):
        await send_missing_image_error(update, context, rune_draws[image_paths.index(None)][0], palette)
        return
    from rune_collage import build_spread_collage
    position_labels = [orientation_label(orientation, rune["key"]) for rune, orientation in rune_draws]
    image_path = build_spread_collage(image_paths, palette, position_labels)

    try:
        from spread_engine_approved import build_unified_spread
        text = build_unified_spread(question, rune_draws, palette, name)
    except Exception:
        # Safety net: if the topic/group-aware engine ever breaks on an
        # unexpected input, fall back to the simpler (but always-correct)
        # rotation-based spread rather than failing the reading outright.
        logger.exception("Approved spread engine failed, falling back")
        try:
            text = generate_rasklad(rune_draws, question, palette, name)
        except KeyError:
            logger.exception("Spread text not found")
            await send_private_or_group(update, context, "Для одной из карт не найден текст расклада в загруженном файле.")
            return

    await send_private_or_group(update, context, text, image_path=image_path, reading_mode=True)


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received text")
    text = (update.effective_message.text or "").strip()

    if not await ensure_profile_ready(update, context):
        return

    if text == "↩ Меню":
        await update.effective_message.reply_text("Меню открыто.", reply_markup=main_keyboard_for(update.effective_user.id))
        return

    if text == "🌞 Руна дня":
        await runa_command(update, context)
        return

    if text in {"❓ Вопрос", "❓ Задать вопрос", "❓ Да / Нет"}:
        context.user_data["state"] = STATE_WAITING_ASK
        await update.effective_message.reply_text("❓ Напиши вопрос — отвечу Да / Нет одной картой.", reply_markup=main_keyboard_for(update.effective_user.id) if is_private(update) else None)
        return

    if text == "🔮 Расклад":
        context.user_data["state"] = STATE_WAITING_RASKLAD
        await update.effective_message.reply_text("🔮 Напиши вопрос — раскину три карты: прошлое / настоящее / будущее.", reply_markup=main_keyboard_for(update.effective_user.id) if is_private(update) else None)
        return

    if text == "ℹ️ Помощь":
        await help_command(update, context)
        return

    state = context.user_data.get("state")
    context.user_data.pop("state", None)

    if state == STATE_WAITING_ASK:
        from product_runtime import product_send_one_rune_answer
        await product_send_one_rune_answer(update, context, text)
        return

    if state == STATE_WAITING_RASKLAD:
        await send_rasklad(update, context, text)
        return

    await update.effective_message.reply_text(
        "Выбери действие на клавиатуре. Или напиши /help, если потерялся.",
        reply_markup=main_keyboard_for(update.effective_user.id) if is_private(update) else private_link_markup(context),
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled bot error", exc_info=context.error)
    if not isinstance(update, Update):
        return
    message = getattr(update, "effective_message", None)
    if message:
        try:
            await message.reply_text(
                "Что-то пошло не так. Попробуй ещё раз — обычно помогает 🙏",
                reply_markup=main_keyboard_for(update.effective_user.id),
            )
        except Exception:
            pass


def build_application() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set. Add it in environment variables.")

    init_db()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("check_decks", check_decks_command))
    app.add_handler(CommandHandler("runa", runa_command))
    app.add_handler(CommandHandler("ask", ask_command))
    app.add_handler(CommandHandler("rasklad", rasklad_command))
    app.add_handler(CallbackQueryHandler(onboarding_callback, pattern=r"^onboarding:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.add_error_handler(error_handler)
    return app


def main() -> None:
    logger.info("BOT_TOKEN set: %s", bool(BOT_TOKEN))
    logger.info("WEBHOOK_URL: %r", WEBHOOK_URL)
    logger.info("PORT: %s", PORT)
    logger.info("DB_PATH: %s", DB_PATH)

    app = build_application()
    if WEBHOOK_URL or IS_CLOUD_RUN:
        logger.info("Starting bot in webhook mode on port %s path /%s", PORT, WEBHOOK_PATH)
        asyncio.run(_run_webhook_with_health(app))
        return

    logger.info("Starting bot in polling mode")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


async def _run_webhook_with_health(app: Application) -> None:
    """Run PTB webhook + a /health endpoint on the same port via starlette+uvicorn."""
    import uvicorn
    from starlette.applications import Starlette
    from starlette.requests import Request as StarletteRequest
    from starlette.responses import PlainTextResponse, Response
    from starlette.routing import Route

    async def telegram_webhook(request: StarletteRequest) -> Response:
        data = await request.json()
        # Keep the Cloud Run request open while PTB handles the update.
        # With request-based billing Cloud Run can throttle CPU as soon as the
        # HTTP response is returned.  Queuing the update and returning first
        # therefore made image composition and Telegram sends run as
        # background work, which could stretch a spread from seconds to
        # minutes on a scale-to-zero instance.
        await app.process_update(Update.de_json(data=data, bot=app.bot))
        return Response()

    async def health(_: StarletteRequest) -> PlainTextResponse:
        return PlainTextResponse("OK")

    starlette_app = Starlette(routes=[
        Route(f"/{WEBHOOK_PATH}", telegram_webhook, methods=["POST"]),
        Route("/health", health, methods=["GET"]),
    ])

    config = uvicorn.Config(app=starlette_app, host="0.0.0.0", port=PORT, log_level="warning")
    server = uvicorn.Server(config)

    async with app:
        await app.start()
        warmup_task = None
        warmup = app.bot_data.get("startup_warmup")
        if warmup:
            warmup_task = asyncio.create_task(warmup())
        if WEBHOOK_URL:
            async def refresh_webhook() -> None:
                try:
                    await app.bot.set_webhook(
                        url=f"{WEBHOOK_URL}/{WEBHOOK_PATH}",
                        allowed_updates=Update.ALL_TYPES,
                        drop_pending_updates=True,
                    )
                    logger.info("Webhook refreshed in background")
                except Exception:
                    logger.exception("Background webhook refresh failed")

            webhook_task = asyncio.create_task(refresh_webhook())
            logger.info("Starting uvicorn immediately; refreshing webhook in background")
        else:
            webhook_task = None
            logger.info("Webhook URL is not configured yet; serving /health on :%s", PORT)
        await server.serve()
        for task in (warmup_task, webhook_task):
            if task and not task.done():
                task.cancel()
        await app.stop()


if __name__ == "__main__":
    main()
