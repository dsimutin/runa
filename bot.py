import logging
import os
import random
from datetime import date
from typing import Any, Dict, List

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from database import (
    DatabaseError,
    ensure_user,
    get_or_create_daily_runes,
    get_user_profile,
    init_db,
    save_onboarding_answer,
    start_onboarding,
)
from rasklad_engine import generate_rasklad
from runes_data import RUNES, get_rune_by_name
from runes_interpretations import PSYCHOTYPES, get_interpretation

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
USE_GPT = os.getenv("USE_GPT", "false").strip().lower() in {"1", "true", "yes", "on"}
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo").strip()
DB_PATH = os.getenv("DB_PATH", "rune_bot.db")
PORT = int(os.getenv("PORT", "10000"))
WEBHOOK_URL = (os.getenv("WEBHOOK_URL") or os.getenv("RENDER_EXTERNAL_URL", "")).strip().rstrip("/")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "webhook").strip().strip("/") or "webhook"


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
DECK_DIRS = {"light": "light", "dark": "dark"}

STATE_WAITING_ASK = "waiting_ask"
STATE_WAITING_RASKLAD = "waiting_rasklad"

ONBOARDING_QUESTIONS = [
    {"text": "Ты заходишь в незнакомое место. Что замечаешь первым?", "a": "Атмосферу: свет, воздух, настроение, людей", "b": "Структуру: входы, выходы, правила, кто контролирует пространство"},
    {"text": "Когда внутри тревожно, что помогает быстрее?", "a": "Побыть в тишине, собрать ощущения, мягко вернуть себя в баланс", "b": "Назвать проблему прямо, принять решение и начать действовать"},
    {"text": "Какой символ тебе ближе прямо сейчас?", "a": "Тёплый луч на закрытой двери", "b": "Золотой ключ в тёмной комнате"},
]

logging.basicConfig(format="%(asctime)s | %(name)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

MAIN_KEYBOARD = ReplyKeyboardMarkup([["🌞 Руна дня", "❓ Вопрос"], ["🔮 Расклад", "ℹ️ Помощь"]], resize_keyboard=True)


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
    logger.info("%s | user_id=%s username=%s chat_id=%s chat_type=%s text=%r", action, user.id if user else None, user.username if user else None, chat.id if chat else None, chat.type if chat else None, message.text if message else None)


def choose_distinct_runes(count: int) -> List[Dict[str, Any]]:
    return random.sample(RUNES, min(count, len(RUNES)))


def bot_link(context: ContextTypes.DEFAULT_TYPE) -> str:
    username = context.application.bot_data.get("bot_username") or "runes2026_bot"
    return f"https://t.me/{username}"


def private_link_markup(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Открыть личку с ботом", url=bot_link(context))]])


def onboarding_keyboard(step: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("A", callback_data=f"onboarding:{step}:light")], [InlineKeyboardButton("B", callback_data=f"onboarding:{step}:dark")]])


def build_onboarding_question(step: int, name: str) -> str:
    question = ONBOARDING_QUESTIONS[step - 1]
    return f"🜂 {name}, выбери вариант\n\nВопрос {step}/3\n{question['text']}\n\nA — {question['a']}\nB — {question['b']}"


def onboarding_result_text(palette: str) -> str:
    profile = PSYCHOTYPES[palette]
    return f"🜂 Колода закреплена\n\nТвоя палитра: {profile['description']}.\n\nСтиль чтения: {profile['reading_style']}.\n\nТеперь можно выбрать действие ниже."


def get_user_palette(update: Update) -> str:
    user = update.effective_user
    if not user:
        return "light"
    try:
        profile = get_user_profile(DB_PATH, user.id)
        if profile and profile.get("palette") in {"light", "dark"}:
            return profile["palette"]
    except DatabaseError:
        logger.exception("Failed to get user palette")
    return "light"


def rune_text(rune: Dict[str, Any], palette: str) -> Dict[str, str]:
    return get_interpretation(rune.get("key", ""), palette, rune)


def get_rune_image_path(rune: Dict[str, Any], palette: str) -> str | None:
    palette_images = rune.get("palette_image_files")
    if palette_images:
        image_file = palette_images.get(palette) or palette_images.get("light")
        deck_dir = DECK_DIRS.get(palette, "light")
        candidates = [os.path.join(BASE_DIR, deck_dir, image_file), os.path.join(BASE_DIR, "decks", deck_dir, image_file)]
        for path in candidates:
            if os.path.exists(path):
                return path
        return None
    image_file = rune.get("image_file")
    if not image_file:
        return None
    deck_dir = DECK_DIRS.get(palette, "light")
    candidates = [os.path.join(BASE_DIR, deck_dir, image_file), os.path.join(BASE_DIR, "decks", deck_dir, image_file)]
    for path in candidates:
        if os.path.exists(path):
            return path
    logger.warning("Rune image not found: palette=%s file=%s", palette, image_file)
    return None


def check_deck_files() -> Dict[str, List[str]]:
    missing: Dict[str, List[str]] = {}
    for palette in ("light", "dark"):
        missing[palette] = []
        for rune in RUNES:
            if not get_rune_image_path(rune, palette):
                missing[palette].append(rune.get("image_file", rune.get("name", "unknown")))
    return missing


def format_daily_message(name: str, main_rune: Dict[str, Any], main_text: Dict[str, str], aux_rune: Dict[str, Any], aux_text: Dict[str, str]) -> str:
    return (
        f"🌞 {name}, руна дня\n\n"
        f"Основная карта — {main_rune['name']}\n"
        f"{main_text['short_desc']}\n\n"
        f"Дополнительный акцент — {aux_rune['name']}\n"
        f"{aux_text['short_desc']}\n\n"
        f"Что сделать сегодня\n"
        f"Выбери один конкретный шаг по основной карте. Дополнительная руна показывает, где не стоит действовать на автомате."
    )


def format_one_rune_answer(name: str, question: str, rune: Dict[str, Any], answer: str, label: str) -> str:
    return (
        f"❓ {name}, ответ\n\n"
        f"Вопрос: {question}\n\n"
        f"Карта — {rune['name']}\n"
        f"Формат — {label}\n\n"
        f"Ответ\n"
        f"{answer}\n\n"
        f"Практический вывод\n"
        f"Используй карту как подсказку: что проверить, где остановиться и какой шаг сделать трезво."
    )


async def ensure_profile_ready(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    message = update.effective_message
    if not user or not message:
        return False
    if not is_private(update):
        return True
    try:
        ensure_user(DB_PATH, user.id, user_name(update))
        profile = get_user_profile(DB_PATH, user.id)
        if profile and profile.get("palette"):
            return True
        step = profile.get("onboarding_step", 0) if profile else 0
        if step <= 0:
            start_onboarding(DB_PATH, user.id)
            step = 1
        await message.reply_text(build_onboarding_question(step, user_name(update)), reply_markup=onboarding_keyboard(step))
        return False
    except DatabaseError:
        logger.exception("Failed to prepare user profile")
        await message.reply_text("Что-то пошло не так. Попробуй ещё раз через минуту.")
        return False


async def send_private_or_group(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, *, image_path: str | None = None) -> None:
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return
    parse_mode = "HTML" if wants_html(text) else None
    plain_text = strip_html(text)
    try:
        if is_private(update):
            if image_path:
                with open(image_path, "rb") as image_file:
                    await message.reply_photo(photo=image_file, caption=text, reply_markup=MAIN_KEYBOARD, parse_mode=parse_mode)
            else:
                await message.reply_text(text, reply_markup=MAIN_KEYBOARD, parse_mode=parse_mode)
            return
        if image_path:
            with open(image_path, "rb") as image_file:
                await context.bot.send_photo(chat_id=user.id, photo=image_file, caption=text, parse_mode=parse_mode)
        else:
            await context.bot.send_message(chat_id=user.id, text=text, parse_mode=parse_mode)
        await message.reply_text("Отправил ответ тебе в личку ✨")
    except BadRequest:
        logger.exception("HTML send failed; retrying plain text")
        try:
            if is_private(update):
                if image_path:
                    with open(image_path, "rb") as image_file:
                        await message.reply_photo(photo=image_file, caption=plain_text, reply_markup=MAIN_KEYBOARD)
                else:
                    await message.reply_text(plain_text, reply_markup=MAIN_KEYBOARD)
                return
            if image_path:
                with open(image_path, "rb") as image_file:
                    await context.bot.send_photo(chat_id=user.id, photo=image_file, caption=plain_text)
            else:
                await context.bot.send_message(chat_id=user.id, text=plain_text)
            await message.reply_text("Отправил ответ тебе в личку ✨")
        except TelegramError:
            logger.exception("Plain fallback failed")
            await message.reply_text("Сообщение не ушло. Давай попробуем ещё раз через минуту.")
    except Forbidden:
        await message.reply_text("Чтобы я мог писать тебе лично, открой со мной личный чат и нажми /start.", reply_markup=private_link_markup(context))
    except (OSError, TelegramError):
        logger.exception("Failed to send response")
        await message.reply_text("Сообщение не ушло. Давай попробуем ещё раз через минуту.")


def short_help() -> str:
    return (
        "ℹ️ <b>Что я умею</b>\n\n"
        "🌞 /runa — вытяну тебе руну дня\n"
        "❓ /ask <i>вопрос</i> — отвечу одной картой\n"
        "🔮 /rasklad <i>вопрос</i> — раскину три карты на ситуацию\n"
        "🜂 /profile — покажу твою колоду\n\n"
        "Если просто нажать кнопку в меню — спрошу вопрос отдельным сообщением."
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /start")
    context.user_data.clear()
    name = user_name(update)
    if not is_private(update):
        await update.effective_message.reply_text("Раскладам нужна личка. Открой со мной личный чат и нажми /start — там и продолжим.", reply_markup=private_link_markup(context))
        return
    try:
        ensure_user(DB_PATH, update.effective_user.id, name)
        profile = get_user_profile(DB_PATH, update.effective_user.id)
        if not profile or not profile.get("palette"):
            start_onboarding(DB_PATH, update.effective_user.id)
            await update.effective_message.reply_text(build_onboarding_question(1, name), reply_markup=onboarding_keyboard(1))
            return
    except DatabaseError:
        logger.exception("Failed to start onboarding")
        await update.effective_message.reply_text("Что-то пошло не так. Попробуй ещё раз через минуту.")
        return
    await update.effective_message.reply_text(f"🜂 {name}, твоя колода уже выбрана.\n\nС чего начнём?", reply_markup=MAIN_KEYBOARD)


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
        result = save_onboarding_answer(DB_PATH, update.effective_user.id, answer, len(ONBOARDING_QUESTIONS))
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
                "🌞  Руна дня — фокус на сегодня\n"
                "❓ Вопрос — быстрый ответ одной картой\n"
                "🔮  Расклад — разбор ситуации (3 карты)\n\n"
                "Выбери действие ниже"
            ),
            reply_markup=MAIN_KEYBOARD,
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
    profile = PSYCHOTYPES[palette]
    text = (
        "🜂 Твой профиль\n\n"
        f"Колода: {'светлая' if palette == 'light' else 'тёмная'}\n"
        f"Стиль: {profile['name']}\n\n"
        f"Как читается:\n{profile['reading_style']}.\n\n"
        "Сброс: удалить чат с ботом и начать заново."
    )
    await send_private_or_group(update, context, text)


async def check_decks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /check_decks")
    if not is_admin(update):
        await update.effective_message.reply_text("Эта техническая команда доступна только администратору.")
        return
    missing = check_deck_files()
    lines = ["🧩 Проверка колод", ""]
    for palette in ("light", "dark"):
        count = len(RUNES) - len(missing[palette])
        title = "светлая" if palette == "light" else "тёмная"
        lines.append(f"{title}: {count}/{len(RUNES)}")
        if missing[palette]:
            lines.append("Не найдены:")
            lines.extend(f"— {name}" for name in missing[palette])
        lines.append("")
    await send_private_or_group(update, context, "\n".join(lines).strip())


async def send_missing_image_error(update: Update, context: ContextTypes.DEFAULT_TYPE, rune: Dict[str, Any], palette: str) -> None:
    await send_private_or_group(update, context, f"Не найдена карта {rune.get('image_file', rune.get('name', ''))} в папке {palette}. Проверь /check_decks.")


async def runa_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /runa")
    context.user_data.clear()
    if not update.effective_user:
        return
    if not await ensure_profile_ready(update, context):
        return
    today = date.today().isoformat()
    try:
        main_name, aux_name = get_or_create_daily_runes(DB_PATH, update.effective_user.id, today, RUNES)
    except DatabaseError:
        logger.exception("Failed to get daily runes")
        await send_private_or_group(update, context, "Сейчас не получается достать руну дня. Попробуй чуть позже.")
        return
    palette = get_user_palette(update)
    main_rune = get_rune_by_name(main_name)
    aux_rune = get_rune_by_name(aux_name)
    image_path = get_rune_image_path(main_rune, palette)
    if not image_path:
        await send_missing_image_error(update, context, main_rune, palette)
        return
    text = format_daily_message(user_name(update), main_rune, rune_text(main_rune, palette), aux_rune, rune_text(aux_rune, palette))
    await send_private_or_group(update, context, text, image_path=image_path)


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /ask")
    if not await ensure_profile_ready(update, context):
        return
    question = " ".join(context.args).strip()
    if not question:
        context.user_data["state"] = STATE_WAITING_ASK
        await update.effective_message.reply_text("❓ Напиши свой вопрос — отвечу одной картой.", reply_markup=MAIN_KEYBOARD if is_private(update) else None)
        return
    await send_one_rune_answer(update, context, question)


async def send_one_rune_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str) -> None:
    if not await ensure_profile_ready(update, context):
        return
    palette = get_user_palette(update)
    rune = random.choice(RUNES)
    image_path = get_rune_image_path(rune, palette)
    if not image_path:
        await send_missing_image_error(update, context, rune, palette)
        return
    text_data = rune_text(rune, palette)
    is_yes = random.random() < 0.5
    label = "совет" if is_yes else "предупреждение"
    answer = text_data["answer_yes"] if is_yes else text_data["answer_no"]
    text = format_one_rune_answer(user_name(update), question, rune, answer, label)
    await send_private_or_group(update, context, text, image_path=image_path)


def build_template_rasklad(name: str, question: str, runes: List[Dict[str, Any]], palette: str) -> str:
    return generate_rasklad(runes, question, palette, name)


def build_gpt_prompt(name: str, question: str, runes: List[Dict[str, Any]]) -> str:
    return f"Ты пишешь короткий трёхрунный расклад на русском языке до 300 символов. Не обещай гарантированный результат.\nИмя: {name}\nВопрос: {question}\nСитуация: {runes[0]['name']} — {runes[0]['meaning_situation']}\nПрепятствие: {runes[1]['name']} — {runes[1]['meaning_obstacle']}\nСовет: {runes[2]['name']} — {runes[2]['meaning_advice']}"


async def build_ai_rasklad(name: str, question: str, runes: List[Dict[str, Any]]) -> str | None:
    if not OPENAI_API_KEY or OpenAI is None:
        return None
    try:
        client = OpenAI(api_key=OPENAI_API_KEY, timeout=20.0)
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Ты помощник для рунических раскладов. Пиши кратко и без категоричных обещаний."},
                {"role": "user", "content": build_gpt_prompt(name, question, runes)},
            ],
            max_tokens=160,
            temperature=0.8,
        )
        content = response.choices[0].message.content
        return content.strip() if content else None
    except Exception:
        logger.exception("OpenAI generation failed; using template rasklad")
        return None


async def rasklad_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /rasklad")
    if not await ensure_profile_ready(update, context):
        return
    question = " ".join(context.args).strip()
    if not question:
        context.user_data["state"] = STATE_WAITING_RASKLAD
        await update.effective_message.reply_text("🔮 Напиши вопрос — раскину три карты.", reply_markup=MAIN_KEYBOARD if is_private(update) else None)
        return
    await send_rasklad(update, context, question)


async def send_rasklad(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str) -> None:
    if not await ensure_profile_ready(update, context):
        return
    name = user_name(update)
    runes = choose_distinct_runes(3)
    palette = get_user_palette(update)
    image_path = get_rune_image_path(runes[2], palette)
    if not image_path:
        await send_missing_image_error(update, context, runes[2], palette)
        return
    text = await build_ai_rasklad(name, question, runes) if USE_GPT else None
    if not text:
        text = build_template_rasklad(name, question, runes, palette)
    await send_private_or_group(update, context, text, image_path=image_path)


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received text")
    text = (update.effective_message.text or "").strip()
    if not await ensure_profile_ready(update, context):
        return
    if text == "🌞 Руна дня":
        await runa_command(update, context)
        return
    if text in {"❓ Вопрос", "❓ Задать вопрос"}:
        context.user_data["state"] = STATE_WAITING_ASK
        await update.effective_message.reply_text("❓ Напиши свой вопрос — отвечу одной картой.", reply_markup=MAIN_KEYBOARD if is_private(update) else None)
        return
    if text == "🔮 Расклад":
        context.user_data["state"] = STATE_WAITING_RASKLAD
        await update.effective_message.reply_text("🔮 Напиши вопрос — раскину три карты.", reply_markup=MAIN_KEYBOARD if is_private(update) else None)
        return
    if text == "ℹ️ Помощь":
        await help_command(update, context)
        return
    state = context.user_data.get("state")
    context.user_data.pop("state", None)
    if state == STATE_WAITING_ASK:
        await send_one_rune_answer(update, context, text)
        return
    if state == STATE_WAITING_RASKLAD:
        await send_rasklad(update, context, text)
        return
    await update.effective_message.reply_text("Выбери действие на клавиатуре. Или напиши /help, если потерялся.", reply_markup=MAIN_KEYBOARD if is_private(update) else private_link_markup(context))


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled bot error", exc_info=context.error)


def build_application() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set. Add it in environment variables.")
    init_db(DB_PATH)
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
    if WEBHOOK_URL:
        logger.info("Starting bot in webhook mode on port %s path /%s", PORT, WEBHOOK_PATH)
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH,
            webhook_url=f"{WEBHOOK_URL}/{WEBHOOK_PATH}",
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
        return
    logger.info("Starting bot in polling mode")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
