import logging
import os
import random
from datetime import date
from typing import List, Dict, Any

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from database import (
    DatabaseError,
    init_db,
    get_or_create_daily_runes,
    get_preferred_name,
    set_preferred_name,
)
from runes_data import RUNES, get_rune_by_name

try:
    from openai import OpenAI
except ImportError:  # openai is optional unless USE_GPT=true
    OpenAI = None


load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
USE_GPT = os.getenv("USE_GPT", "false").strip().lower() in {"1", "true", "yes", "on"}
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo").strip()

DB_PATH = os.getenv("DB_PATH", "rune_bot.db")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "telegram-webhook").strip("/")
PORT = int(os.getenv("PORT", "10000"))

ASK_NAME = 1

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def tg_first_name(update: Update) -> str:
    """Return a friendly fallback name from Telegram profile."""
    user = update.effective_user
    if not user:
        return "друг"
    return user.first_name or user.username or "друг"


def get_user_name(update: Update) -> str:
    """Return saved preferred name or Telegram first name."""
    user_id = update.effective_user.id
    saved_name = get_preferred_name(DB_PATH, user_id)
    return saved_name or tg_first_name(update)


def choose_distinct_runes(count: int) -> List[Dict[str, Any]]:
    """Choose distinct runes when possible."""
    if count >= len(RUNES):
        return random.sample(RUNES, len(RUNES))
    return random.sample(RUNES, count)


def format_help() -> str:
    return (
        "✨ Команды бота:\n\n"
        "/start — приветствие и настройка имени\n"
        "/runa — руна дня + вспомогательная руна\n"
        "/ask <вопрос> — ответ одной руной\n"
        "/rasklad <вопрос> — трёхрунный расклад: ситуация → препятствие → совет\n"
        "/help — справка\n\n"
        "Примеры:\n"
        "/ask Стоит ли начинать новый проект?\n"
        "/rasklad Как улучшить отношения?"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start command. Ask for name if it is not saved yet."""
    user_id = update.effective_user.id
    name = get_preferred_name(DB_PATH, user_id)

    if not name:
        await update.message.reply_text(
            "Привет! Я рунический оракул ✨\n\n"
            "Как мне к тебе обращаться? Напиши имя одним сообщением."
        )
        return ASK_NAME

    await update.message.reply_text(
        f"Привет, {name}! ✨\n\n"
        "Я могу дать руну дня, ответить на вопрос одной руной "
        "или сделать трёхрунный расклад.\n\n"
        f"{format_help()}"
    )
    return ConversationHandler.END


async def save_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save preferred user name after /start."""
    user_id = update.effective_user.id
    name = (update.message.text or "").strip()

    if not name:
        await update.message.reply_text("Напиши имя текстом, пожалуйста.")
        return ASK_NAME

    if len(name) > 50:
        await update.message.reply_text("Имя слишком длинное. Напиши короткий вариант.")
        return ASK_NAME

    try:
        set_preferred_name(DB_PATH, user_id, name)
    except DatabaseError:
        logger.exception("Failed to save user name")
        await update.message.reply_text("Не получилось сохранить имя. Попробуй ещё раз позже.")
        return ConversationHandler.END

    await update.message.reply_text(
        f"Отлично, {name}! Запомнил ✨\n\n"
        f"{format_help()}"
    )
    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(format_help())


async def runa_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show daily main rune and auxiliary rune fixed per user/day."""
    user_id = update.effective_user.id
    today = date.today().isoformat()

    try:
        main_name, aux_name = get_or_create_daily_runes(DB_PATH, user_id, today, RUNES)
    except DatabaseError:
        logger.exception("Failed to get daily runes")
        await update.message.reply_text("Ошибка базы данных. Попробуй ещё раз немного позже.")
        return

    main_rune = get_rune_by_name(main_name)
    aux_rune = get_rune_by_name(aux_name)

    text = (
        f"🌞 Твоя руна дня: {main_rune['name']}\n"
        f"{main_rune['short_desc']}\n\n"
        f"🔮 Вспомогательная руна: {aux_rune['name']}\n"
        f"{aux_rune['short_desc']}\n\n"
        "Вспомогательная руна показывает дополнительную энергию дня: "
        "что усилит действие или на что стоит обратить внимание."
    )
    await update.message.reply_text(text)


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Answer user's question with one random rune."""
    question = " ".join(context.args).strip()

    if not question:
        await update.message.reply_text("Напиши вопрос после команды, например: /ask Стоит ли начинать новый проект?")
        return

    rune = random.choice(RUNES)
    use_yes = random.random() < 0.5
    answer = rune["answer_yes"] if use_yes else rune["answer_no"]
    answer_type = "развёрнутый совет" if use_yes else "короткий ответ"

    text = (
        f"❓ Вопрос: {question}\n\n"
        f"ᚱ Руна ответа: {rune['name']}\n"
        f"Тип ответа: {answer_type}\n\n"
        f"{answer}"
    )
    await update.message.reply_text(text)


def build_template_rasklad(name: str, question: str, runes: List[Dict[str, Any]]) -> str:
    """Build a connected three-rune spread without AI."""
    situation, obstacle, advice = runes

    return (
        f"{name}, расклад на вопрос: «{question}»\n\n"
        f"1. Ситуация — {situation['name']}\n"
        f"{situation['meaning_situation']}\n\n"
        f"2. Препятствие — {obstacle['name']}\n"
        f"{obstacle['meaning_obstacle']}\n\n"
        f"3. Совет — {advice['name']}\n"
        f"{advice['meaning_advice']}\n\n"
        f"Итог: сейчас важнее всего увидеть реальное положение дел, "
        f"не усиливать слабое место и действовать через совет руны {advice['name']}."
    )


def build_gpt_prompt(name: str, question: str, runes: List[Dict[str, Any]]) -> str:
    """Prepare compact prompt for AI-based spread."""
    return (
        "Ты пишешь короткий мистический, но понятный трёхрунный расклад на русском языке. "
        "Не обещай гарантированный результат. Ответ должен быть до 300 символов. "
        "Обратись к пользователю по имени. "
        "Позиции: ситуация → препятствие → совет.\n\n"
        f"Имя: {name}\n"
        f"Вопрос: {question}\n"
        f"Ситуация: {runes[0]['name']} — {runes[0]['meaning_situation']}\n"
        f"Препятствие: {runes[1]['name']} — {runes[1]['meaning_obstacle']}\n"
        f"Совет: {runes[2]['name']} — {runes[2]['meaning_advice']}"
    )


async def build_ai_rasklad(name: str, question: str, runes: List[Dict[str, Any]]) -> str:
    """Build a spread with OpenAI API when USE_GPT=true."""
    if not OPENAI_API_KEY or OpenAI is None:
        return "Функция расклада с AI временно недоступна, используйте /ask или /runa"

    client = OpenAI(api_key=OPENAI_API_KEY)
    prompt = build_gpt_prompt(name, question, runes)

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": "Ты помощник для рунических раскладов. Пиши мягко, кратко и без категоричных обещаний."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=120,
        temperature=0.8,
    )
    return response.choices[0].message.content.strip()


async def rasklad_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Three-rune spread: situation, obstacle, advice."""
    question = " ".join(context.args).strip()

    if not question:
        await update.message.reply_text("Напиши вопрос после команды, например: /rasklad Как улучшить отношения?")
        return

    name = get_user_name(update)
    runes = choose_distinct_runes(3)

    try:
        if USE_GPT:
            text = await build_ai_rasklad(name, question, runes)
        else:
            text = build_template_rasklad(name, question, runes)
    except Exception:
        logger.exception("Failed to build rasklad")
        await update.message.reply_text("Не получилось сделать расклад. Попробуй ещё раз позже.")
        return

    await update.message.reply_text(text)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log all unhandled errors."""
    logger.exception("Unhandled error while processing update", exc_info=context.error)


def build_application() -> Application:
    """Create Telegram application and register handlers."""
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set. Add it to .env or environment variables.")

    init_db(DB_PATH)

    app = Application.builder().token(BOT_TOKEN).build()

    start_conversation = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_name),
            ]
        },
        fallbacks=[
            CommandHandler("help", help_command),
            CommandHandler("start", start),
        ],
    )

    app.add_handler(start_conversation)
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("runa", runa_command))
    app.add_handler(CommandHandler("ask", ask_command))
    app.add_handler(CommandHandler("rasklad", rasklad_command))
    app.add_error_handler(error_handler)

    return app


def main() -> None:
    app = build_application()

    if WEBHOOK_URL:
        webhook_url = f"{WEBHOOK_URL}/{WEBHOOK_PATH}"
        logger.info("Starting bot in webhook mode on port %s, path /%s", PORT, WEBHOOK_PATH)
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH,
            webhook_url=webhook_url,
            drop_pending_updates=True,
        )
    else:
        logger.info("Starting bot in polling mode")
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
