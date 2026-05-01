import logging
import os
import random
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from database import (
    DatabaseError,
    get_or_create_daily_runes,
    get_preferred_name,
    init_db,
    set_preferred_name,
)
from runes_data import RUNES, get_rune_by_name

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

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


class HealthHandler(BaseHTTPRequestHandler):
    """Simple HTTP endpoint for Render health/port detection."""

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Rune bot is running")

    def do_HEAD(self) -> None:
        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


def start_health_server() -> None:
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("Health server started on port %s", PORT)


async def post_init(application: Application) -> None:
    """Clear old webhook and log the exact Telegram bot connected to this token."""
    await application.bot.delete_webhook(drop_pending_updates=False)
    me = await application.bot.get_me()
    logger.info("Telegram bot connected: id=%s username=@%s name=%s", me.id, me.username, me.first_name)


async def post_shutdown(application: Application) -> None:
    logger.info("Application shutdown complete")


def user_display_name(update: Update) -> str:
    user = update.effective_user
    if not user:
        return "друг"

    try:
        saved_name = get_preferred_name(DB_PATH, user.id)
    except DatabaseError:
        logger.exception("Failed to read preferred name")
        saved_name = None

    return saved_name or user.first_name or user.username or "друг"


def telegram_name(update: Update) -> str:
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


def format_help() -> str:
    return (
        "✨ Я рунический оракул.\n\n"
        "Команды:\n"
        "/start — запустить бота\n"
        "/runa — руна дня + вспомогательная руна\n"
        "/ask <вопрос> — ответ одной руной\n"
        "/rasklad <вопрос> — трёхрунный расклад\n"
        "/name <имя> — сохранить имя\n"
        "/help — справка\n\n"
        "Примеры:\n"
        "/ask Стоит ли начинать новый проект?\n"
        "/rasklad Как улучшить отношения?"
    )


def choose_distinct_runes(count: int) -> List[Dict[str, Any]]:
    return random.sample(RUNES, min(count, len(RUNES)))


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /start")
    name = telegram_name(update)

    if update.effective_user:
        try:
            set_preferred_name(DB_PATH, update.effective_user.id, name)
        except DatabaseError:
            logger.exception("Failed to save Telegram name")

    await update.effective_message.reply_text(
        f"Привет, {name}! ✨\n\n"
        "Бот работает. Можешь сразу использовать команды.\n\n"
        f"{format_help()}"
    )


async def name_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /name")
    if not update.effective_user:
        return

    name = " ".join(context.args).strip()
    if not name:
        await update.effective_message.reply_text("Напиши имя после команды, например: /name Дима")
        return

    if len(name) > 50:
        await update.effective_message.reply_text("Имя слишком длинное. Напиши короткий вариант.")
        return

    try:
        set_preferred_name(DB_PATH, update.effective_user.id, name)
    except DatabaseError:
        logger.exception("Failed to save preferred name")
        await update.effective_message.reply_text("Ошибка базы данных. Имя не сохранилось.")
        return

    await update.effective_message.reply_text(f"Готово, {name}. Запомнил ✨")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /help")
    await update.effective_message.reply_text(format_help())


async def runa_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /runa")
    if not update.effective_user:
        return

    today = date.today().isoformat()
    try:
        main_name, aux_name = get_or_create_daily_runes(DB_PATH, update.effective_user.id, today, RUNES)
    except DatabaseError:
        logger.exception("Failed to get daily runes")
        await update.effective_message.reply_text("Ошибка базы данных. Попробуй позже.")
        return

    main_rune = get_rune_by_name(main_name)
    aux_rune = get_rune_by_name(aux_name)

    await update.effective_message.reply_text(
        f"🌞 Твоя руна дня: {main_rune['name']}\n"
        f"{main_rune['short_desc']}\n\n"
        f"🔮 Вспомогательная руна: {aux_rune['name']}\n"
        f"{aux_rune['short_desc']}\n\n"
        "Вспомогательная руна — дополнительная энергия дня: что усилит действие или на что обратить внимание."
    )


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /ask")
    question = " ".join(context.args).strip()

    if not question:
        await update.effective_message.reply_text("Напиши вопрос после команды, например: /ask Стоит ли начинать новый проект?")
        return

    rune = random.choice(RUNES)
    answer = rune["answer_yes"] if random.random() < 0.5 else rune["answer_no"]

    await update.effective_message.reply_text(
        f"❓ Вопрос: {question}\n\n"
        f"ᚱ Руна ответа: {rune['name']}\n\n"
        f"{answer}"
    )


def build_template_rasklad(name: str, question: str, runes: List[Dict[str, Any]]) -> str:
    situation, obstacle, advice = runes
    return (
        f"{name}, расклад на вопрос: «{question}»\n\n"
        f"1. Ситуация — {situation['name']}\n{situation['meaning_situation']}\n\n"
        f"2. Препятствие — {obstacle['name']}\n{obstacle['meaning_obstacle']}\n\n"
        f"3. Совет — {advice['name']}\n{advice['meaning_advice']}\n\n"
        f"Итог: не форсируй слабое место и действуй через совет руны {advice['name']}."
    )


def build_gpt_prompt(name: str, question: str, runes: List[Dict[str, Any]]) -> str:
    return (
        "Ты пишешь короткий трёхрунный расклад на русском языке до 300 символов. "
        "Не обещай гарантированный результат. Обратись к пользователю по имени.\n\n"
        f"Имя: {name}\n"
        f"Вопрос: {question}\n"
        f"Ситуация: {runes[0]['name']} — {runes[0]['meaning_situation']}\n"
        f"Препятствие: {runes[1]['name']} — {runes[1]['meaning_obstacle']}\n"
        f"Совет: {runes[2]['name']} — {runes[2]['meaning_advice']}"
    )


async def build_ai_rasklad(name: str, question: str, runes: List[Dict[str, Any]]) -> str:
    if not OPENAI_API_KEY or OpenAI is None:
        return "Функция расклада с AI временно недоступна, используйте /ask или /runa"

    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": "Ты помощник для рунических раскладов. Пиши кратко и без категоричных обещаний."},
            {"role": "user", "content": build_gpt_prompt(name, question, runes)},
        ],
        max_tokens=120,
        temperature=0.8,
    )
    return response.choices[0].message.content.strip()


async def rasklad_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /rasklad")
    question = " ".join(context.args).strip()

    if not question:
        await update.effective_message.reply_text("Напиши вопрос после команды, например: /rasklad Как улучшить отношения?")
        return

    name = user_display_name(update)
    runes = choose_distinct_runes(3)

    try:
        text = await build_ai_rasklad(name, question, runes) if USE_GPT else build_template_rasklad(name, question, runes)
    except Exception:
        logger.exception("Failed to build rasklad")
        await update.effective_message.reply_text("Не получилось сделать расклад. Попробуй позже.")
        return

    await update.effective_message.reply_text(text)


async def fallback_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Respond to any plain text. This proves updates are reaching the bot."""
    log_update(update, "Received plain text")
    await update.effective_message.reply_text(
        "Я на связи ✅\n\n"
        "Используй команды: /runa, /ask <вопрос>, /rasklad <вопрос>."
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled bot error", exc_info=context.error)


def build_application() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set. Add it in Render Environment variables.")

    init_db(DB_PATH)

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("name", name_command))
    app.add_handler(CommandHandler("runa", runa_command))
    app.add_handler(CommandHandler("ask", ask_command))
    app.add_handler(CommandHandler("rasklad", rasklad_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_text))
    app.add_error_handler(error_handler)
    return app


def main() -> None:
    start_health_server()
    app = build_application()
    logger.info("Starting bot in polling mode")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
        close_loop=False,
    )


if __name__ == "__main__":
    main()
