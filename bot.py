import logging
import os
import random
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List

from dotenv import load_dotenv
from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from database import DatabaseError, get_or_create_daily_runes, init_db
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

STATE_WAITING_ASK = "waiting_ask"
STATE_WAITING_RASKLAD = "waiting_rasklad"

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["🌞 Руна дня", "❓ Задать вопрос"],
        ["🔮 Расклад", "ℹ️ Помощь"],
    ],
    resize_keyboard=True,
)


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


def choose_distinct_runes(count: int) -> List[Dict[str, Any]]:
    return random.sample(RUNES, min(count, len(RUNES)))


def short_help() -> str:
    return (
        "Выбери действие кнопкой или используй команды:\n\n"
        "🌞 /runa — руна дня\n"
        "❓ /ask <вопрос> — ответ одной руной\n"
        "🔮 /rasklad <вопрос> — расклад на 3 руны\n"
        "ℹ️ /help — помощь"
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /start")
    context.user_data.clear()
    name = user_name(update)
    await update.effective_message.reply_text(
        f"Привет, {name} ✨\n\n"
        "Я рунический оракул. Могу дать руну дня, ответить на вопрос или сделать расклад.\n\n"
        "Выбери действие ниже:",
        reply_markup=MAIN_KEYBOARD,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /help")
    context.user_data.clear()
    await update.effective_message.reply_text(short_help(), reply_markup=MAIN_KEYBOARD)


async def runa_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /runa")
    context.user_data.clear()
    if not update.effective_user:
        return

    today = date.today().isoformat()
    try:
        main_name, aux_name = get_or_create_daily_runes(DB_PATH, update.effective_user.id, today, RUNES)
    except DatabaseError:
        logger.exception("Failed to get daily runes")
        await update.effective_message.reply_text("Не получилось достать руну дня. Попробуй позже.", reply_markup=MAIN_KEYBOARD)
        return

    main_rune = get_rune_by_name(main_name)
    aux_rune = get_rune_by_name(aux_name)
    name = user_name(update)

    await update.effective_message.reply_text(
        f"🌞 {name}, твоя руна дня — {main_rune['name']}\n\n"
        f"{main_rune['short_desc']}\n\n"
        f"🔮 Дополнительная энергия — {aux_rune['name']}\n\n"
        f"{aux_rune['short_desc']}",
        reply_markup=MAIN_KEYBOARD,
    )


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /ask")
    question = " ".join(context.args).strip()
    if not question:
        context.user_data["state"] = STATE_WAITING_ASK
        await update.effective_message.reply_text(
            "Напиши вопрос одним сообщением. Я отвечу одной руной.",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    await send_one_rune_answer(update, question)


async def send_one_rune_answer(update: Update, question: str) -> None:
    rune = random.choice(RUNES)
    is_yes = random.random() < 0.5
    answer = rune["answer_yes"] if is_yes else rune["answer_no"]
    label = "совет" if is_yes else "предупреждение"
    name = user_name(update)

    await update.effective_message.reply_text(
        f"❓ {name}, вопрос: {question}\n\n"
        f"ᚱ Руна ответа — {rune['name']}\n"
        f"Тип: {label}\n\n"
        f"{answer}",
        reply_markup=MAIN_KEYBOARD,
    )


def build_template_rasklad(name: str, question: str, runes: List[Dict[str, Any]]) -> str:
    situation, obstacle, advice = runes
    return (
        f"🔮 {name}, расклад на вопрос:\n«{question}»\n\n"
        f"1. Ситуация — {situation['name']}\n{situation['meaning_situation']}\n\n"
        f"2. Препятствие — {obstacle['name']}\n{obstacle['meaning_obstacle']}\n\n"
        f"3. Совет — {advice['name']}\n{advice['meaning_advice']}\n\n"
        f"Итог: главный ключ сейчас — {advice['name']}. Не форсируй слабое место, действуй точнее."
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
        return "Функция расклада с AI временно недоступна, используйте /ask или /runa."

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
        context.user_data["state"] = STATE_WAITING_RASKLAD
        await update.effective_message.reply_text(
            "Напиши вопрос одним сообщением. Я сделаю расклад: ситуация → препятствие → совет.",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    await send_rasklad(update, question)


async def send_rasklad(update: Update, question: str) -> None:
    name = user_name(update)
    runes = choose_distinct_runes(3)

    try:
        text = await build_ai_rasklad(name, question, runes) if USE_GPT else build_template_rasklad(name, question, runes)
    except Exception:
        logger.exception("Failed to build rasklad")
        await update.effective_message.reply_text("Не получилось сделать расклад. Попробуй позже.", reply_markup=MAIN_KEYBOARD)
        return

    await update.effective_message.reply_text(text, reply_markup=MAIN_KEYBOARD)


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received text")
    text = (update.effective_message.text or "").strip()

    if text == "🌞 Руна дня":
        await runa_command(update, context)
        return
    if text == "❓ Задать вопрос":
        context.user_data["state"] = STATE_WAITING_ASK
        await update.effective_message.reply_text("Напиши вопрос одним сообщением. Я отвечу одной руной.", reply_markup=MAIN_KEYBOARD)
        return
    if text == "🔮 Расклад":
        context.user_data["state"] = STATE_WAITING_RASKLAD
        await update.effective_message.reply_text(
            "Напиши вопрос одним сообщением. Я сделаю расклад: ситуация → препятствие → совет.",
            reply_markup=MAIN_KEYBOARD,
        )
        return
    if text == "ℹ️ Помощь":
        await help_command(update, context)
        return

    state = context.user_data.get("state")
    context.user_data.pop("state", None)

    if state == STATE_WAITING_ASK:
        await send_one_rune_answer(update, text)
        return
    if state == STATE_WAITING_RASKLAD:
        await send_rasklad(update, text)
        return

    await update.effective_message.reply_text(
        "Я на связи ✨\n\nВыбери действие кнопкой ниже или напиши /help.",
        reply_markup=MAIN_KEYBOARD,
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled bot error", exc_info=context.error)


def build_application() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set. Add it in Render Environment variables.")

    init_db(DB_PATH)

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("runa", runa_command))
    app.add_handler(CommandHandler("ask", ask_command))
    app.add_handler(CommandHandler("rasklad", rasklad_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
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
