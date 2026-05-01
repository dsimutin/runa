import io
import logging
import os
import random
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, ReplyKeyboardMarkup, Update
from telegram.error import Forbidden
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
from runes_interpretations import PSYCHOTYPES

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

RUNE_SYMBOLS = {
    "Феху": "ᚠ", "Уруз": "ᚢ", "Турисаз": "ᚦ", "Ансуз": "ᚨ", "Райдо": "ᚱ", "Кеназ": "ᚲ",
    "Гебо": "ᚷ", "Вуньо": "ᚹ", "Хагалаз": "ᚺ", "Наутиз": "ᚾ", "Иса": "ᛁ", "Йера": "ᛃ",
    "Эйваз": "ᛇ", "Перт": "ᛈ", "Альгиз": "ᛉ", "Соулу": "ᛊ", "Тейваз": "ᛏ", "Беркана": "ᛒ",
    "Эваз": "ᛖ", "Манназ": "ᛗ", "Лагуз": "ᛚ", "Ингуз": "ᛜ", "Дагаз": "ᛞ", "Одал": "ᛟ",
}

ONBOARDING_QUESTIONS = [
    {
        "text": "Ты заходишь в незнакомое место. Что замечаешь первым?",
        "a": "Атмосферу: свет, воздух, настроение, людей",
        "b": "Структуру: входы, выходы, правила, кто контролирует пространство",
    },
    {
        "text": "Когда внутри тревожно, что помогает быстрее?",
        "a": "Побыть в тишине, собрать ощущения, мягко вернуть себя в баланс",
        "b": "Назвать проблему прямо, принять решение и начать действовать",
    },
    {
        "text": "Какой символ тебе ближе прямо сейчас?",
        "a": "Тёплый луч на закрытой двери",
        "b": "Золотой ключ в тёмной комнате",
    },
]

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["🌞 Руна дня", "❓ Вопрос"],
        ["🔮 Расклад", "ℹ️ Помощь"],
    ],
    resize_keyboard=True,
)


def is_private(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.type == "private")


class HealthHandler(BaseHTTPRequestHandler):
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
    await application.bot.delete_webhook(drop_pending_updates=False)
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


def choose_distinct_runes(count: int) -> List[Dict[str, Any]]:
    return random.sample(RUNES, min(count, len(RUNES)))


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
        ]
    )


def build_onboarding_question(step: int, name: str) -> str:
    question = ONBOARDING_QUESTIONS[step - 1]
    return (
        f"{name}, сначала настроим твою колоду.\n\n"
        f"Вопрос {step}/3\n"
        f"{question['text']}\n\n"
        f"A — {question['a']}\n"
        f"B — {question['b']}"
    )


def onboarding_result_text(palette: str) -> str:
    profile = PSYCHOTYPES[palette]
    return (
        "Твоя колода настроена.\n\n"
        f"Тебе открылась {profile['description']}.\n"
        f"Я буду читать руны через {profile['reading_style']}.\n\n"
        "Теперь можно выбрать действие ниже."
    )


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
