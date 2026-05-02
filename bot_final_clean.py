# -*- coding: utf-8 -*-
"""Complete clean Telegram rune bot.

Start Command on Render:
    python bot_final_clean.py

Required env:
    BOT_TOKEN

Features:
- private replies only for user-sensitive readings
- group commands redirect user to private chat
- light/dark palette per user
- daily rune + auxiliary rune
- /ask and /rasklad
- expanded texts from runes_expanded_full.py
- typing delay
- follow-up clarification after spread
"""

import asyncio
import logging
import os
import random
import sqlite3
from datetime import date
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.constants import ChatAction
from telegram.error import BadRequest, Forbidden
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from runes_data import RUNES, get_rune_by_name
from runes_interpretations import get_interpretation

try:
    from runes_expanded_full import get_topic_text, get_variant
except Exception:
    get_topic_text = None
    get_variant = None

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "rune_bot.db")
BASE_DIR = Path(__file__).resolve().parent

STATE_ASK = "ask"
STATE_RASKLAD = "rasklad"
STATE_FOLLOWUP = "followup"

MAIN_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("🌞 Руна дня", callback_data="runa")],
    [InlineKeyboardButton("❓ Вопрос", callback_data="ask")],
    [InlineKeyboardButton("🔮 Расклад", callback_data="rasklad")],
])

PALETTE_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("Светлая", callback_data="palette_light")],
    [InlineKeyboardButton("Тёмная", callback_data="palette_dark")],
])

QUESTION_KEYWORDS = {
    "work": ["работ", "проект", "деньг", "финанс", "бизнес", "клиент", "доход", "карьер", "зарплат"],
    "love": ["отнош", "любов", "муж", "жена", "парень", "девуш", "партнер", "партнёр", "семь", "бывш"],
    "health": ["здоров", "тело", "самочув", "тревог", "устал", "энерг", "сон", "бол"],
    "choice": ["выбор", "выбрать", "решить", "стоит ли", "как поступить", "переезд", "остаться", "уехать"],
}


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, palette TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS rune_day (user_id INTEGER, date TEXT, main_rune TEXT, aux_rune TEXT, PRIMARY KEY(user_id, date))")
    conn.commit()
    conn.close()


def get_user_palette(user_id: int) -> str | None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT palette FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row and row[0] in ("light", "dark") else None


def set_user_palette(user_id: int, palette: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO users(user_id, palette) VALUES (?, ?)", (user_id, palette))
    conn.commit()
    conn.close()


def get_or_create_daily(user_id: int) -> tuple[str, str]:
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT main_rune, aux_rune FROM rune_day WHERE user_id=? AND date=?", (user_id, today))
    row = cur.fetchone()
    if row:
        conn.close()
        return row[0], row[1]
    main, aux = random.sample(RUNES, 2)
    cur.execute("INSERT OR REPLACE INTO rune_day(user_id, date, main_rune, aux_rune) VALUES (?, ?, ?, ?)", (user_id, today, main["name"], aux["name"]))
    conn.commit()
    conn.close()
    return main["name"], aux["name"]


def is_private(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.type == "private")


def bot_link(context: ContextTypes.DEFAULT_TYPE) -> str:
    username = context.application.bot_data.get("bot_username") or "runes2026_bot"
    return f"https://t.me/{username}"


def open_private_markup(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Открыть личку с ботом", url=bot_link(context))]])


def question_type(question: str) -> str:
    q = question.lower()
    for kind, words in QUESTION_KEYWORDS.items():
        if any(w in q for w in words):
            return kind
    return "general"


def stable_index(*parts: object, modulo: int = 3) -> int:
    seed = "|".join(str(p) for p in parts)
    return sum(ord(ch) for ch in seed) % modulo


def rune_text(rune: dict, palette: str, field: str) -> str:
    data = get_interpretation(rune.get("key", ""), palette, rune)
    return data.get(field) or rune.get(field) or rune.get("short_desc") or "Смысл этой руны пока уточняется."


def expanded_text(rune: dict, palette: str, topic: str, field: str) -> str:
    fallback = rune_text(rune, palette, field)
    if get_topic_text is None:
        return fallback
    return get_topic_text(rune.get("key", ""), palette, topic, field, fallback)


def daily_text(rune: dict, palette: str, user_id: int) -> str:
    fallback = rune_text(rune, palette, "short_desc")
    if get_variant is None:
        return fallback
    idx = stable_index(user_id, date.today().isoformat(), rune.get("key", ""), modulo=3)
    return get_variant(rune.get("key", ""), palette, "daily_variants", idx, fallback)


def aux_text(rune: dict, palette: str, user_id: int) -> str:
    fallback = rune_text(rune, palette, "short_desc")
    if get_variant is None:
        return fallback
    idx = stable_index(user_id, date.today().isoformat(), rune.get("key", ""), "aux", modulo=2)
    return get_variant(rune.get("key", ""), palette, "aux_variants", idx, fallback)


def image_path(rune: dict, palette: str) -> Path | None:
    filename = rune.get("image_file")
    if not filename:
        return None
    candidates = [BASE_DIR / palette / filename, BASE_DIR / "images" / palette / filename, BASE_DIR / "decks" / palette / filename]
    for path in candidates:
        if path.exists():
            return path
    return None


async def post_init(app) -> None:
    await app.bot.delete_webhook(drop_pending_updates=False)
    me = await app.bot.get_me()
    app.bot_data["bot_username"] = me.username
    logger.info("Bot connected as @%s", me.username)


async def thinking(update: Update, context: ContextTypes.DEFAULT_TYPE, seconds: float = 1.1) -> None:
    try:
        chat_id = update.effective_user.id if update.effective_user else update.effective_chat.id
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        await asyncio.sleep(seconds)
    except Exception:
        pass


async def send_private(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, rune: dict | None = None) -> None:
    user = update.effective_user
    if not user:
        return
    palette = get_user_palette(user.id) or "light"
    path = image_path(rune, palette) if rune else None
    try:
        if path:
            with path.open("rb") as f:
                await context.bot.send_photo(chat_id=user.id, photo=InputFile(f), caption=text, reply_markup=MAIN_KEYBOARD, parse_mode="Markdown")
        else:
            await context.bot.send_message(chat_id=user.id, text=text, reply_markup=MAIN_KEYBOARD, parse_mode="Markdown")
    except BadRequest:
        await context.bot.send_message(chat_id=user.id, text=text.replace("*", ""), reply_markup=MAIN_KEYBOARD)


async def maybe_redirect_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if is_private(update):
        return False
    try:
        await context.bot.send_message(chat_id=update.effective_user.id, text="Я отправлю ответ сюда, в личную переписку. Так расклад не будет виден группе.", reply_markup=MAIN_KEYBOARD)
        if update.effective_message:
            await update.effective_message.reply_text("Я написал тебе в личку ✨")
    except Forbidden:
        if update.effective_message:
            await update.effective_message.reply_text("Сначала открой личку с ботом и нажми /start.", reply_markup=open_private_markup(context))
        return True
    return False


async def ensure_palette(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str | None:
    user = update.effective_user
    if not user:
        return None
    palette = get_user_palette(user.id)
    if palette:
        return palette
    try:
        await context.bot.send_message(chat_id=user.id, text="Выбери палитру колоды. От этого зависит стиль чтения:", reply_markup=PALETTE_KEYBOARD)
    except Forbidden:
        if update.effective_message:
            await update.effective_message.reply_text("Открой личку с ботом и нажми /start, чтобы выбрать колоду.", reply_markup=open_private_markup(context))
    return None


async def show_main_menu(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_message(chat_id=user_id, text="👇 Что можно сделать:\n\n🌞 Руна дня — фокус на сегодня\n❓ Вопрос — быстрый ответ одной картой\n🔮 Расклад — ситуация, препятствие и шаг\n\nВыбери действие ниже.", reply_markup=MAIN_KEYBOARD)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await maybe_redirect_group(update, context):
        return
    user = update.effective_user
    palette = get_user_palette(user.id)
    if not palette:
        await context.bot.send_message(chat_id=user.id, text="Выбери палитру колоды. Светлая — мягче, тёмная — прямее.", reply_markup=PALETTE_KEYBOARD)
        return
    await show_main_menu(user.id, context)


async def palette_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    palette = "light" if query.data == "palette_light" else "dark"
    set_user_palette(user_id, palette)
    label = "светлая" if palette == "light" else "тёмная"
    await context.bot.send_message(chat_id=user_id, text=f"Колода закреплена: {label}.")
    await show_main_menu(user_id, context)


async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    palette = get_user_palette(user_id)
    if not palette:
        await context.bot.send_message(user_id, "Сначала выбери палитру.", reply_markup=PALETTE_KEYBOARD)
        return
    if query.data == "runa":
        await send_runa_day(update, context)
    elif query.data == "ask":
        context.user_data["state"] = STATE_ASK
        await context.bot.send_message(user_id, "Напиши вопрос одним сообщением. Я отвечу одной руной.")
    elif query.data == "rasklad":
        context.user_data["state"] = STATE_RASKLAD
        await context.bot.send_message(user_id, "Напиши вопрос для расклада одним сообщением.")


async def send_runa_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    palette = await ensure_palette(update, context)
    if not user or not palette:
        return
    main_name, aux_name = get_or_create_daily(user.id)
    main = get_rune_by_name(main_name)
    aux = get_rune_by_name(aux_name)
    await thinking(update, context, 1.0)
    text = f"🌞 **Твоя руна дня — {main['name']}**\n\n{daily_text(main, palette, user.id)}\n\n**Дополнительный акцент — {aux['name']}**\n\n{aux_text(aux, palette, user.id)}\n\n**Что сделать сегодня**\nВыбери один конкретный шаг. Не весь путь целиком — только то, что можно сделать сейчас."
    await send_private(update, context, text, main)


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await maybe_redirect_group(update, context):
        return
    if not await ensure_palette(update, context):
        return
    question = " ".join(context.args).strip()
    if not question:
        context.user_data["state"] = STATE_ASK
        await context.bot.send_message(update.effective_user.id, "Напиши вопрос одним сообщением.")
        return
    await one_answer(update, context, question)


async def one_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str) -> None:
    user = update.effective_user
    palette = await ensure_palette(update, context)
    if not user or not palette:
        return
    context.user_data.pop("state", None)
    topic = question_type(question)
    rune = random.choice(RUNES)
    field = "answer_yes" if random.random() < 0.5 else "answer_no"
    await thinking(update, context, 1.1)
    text = f"❓ **Разбираю вопрос:**\n«{question}»\n\n**Карта — {rune['name']}**\n\n**Ответ**\n{expanded_text(rune, palette, topic, field)}\n\n**Что дальше**\nСмотри не только на ответ, но и на ближайший шаг, который он предлагает."
    await send_private(update, context, text, rune)


async def rasklad_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await maybe_redirect_group(update, context):
        return
    if not await ensure_palette(update, context):
        return
    question = " ".join(context.args).strip()
    if not question:
        context.user_data["state"] = STATE_RASKLAD
        await context.bot.send_message(update.effective_user.id, "Напиши вопрос для расклада одним сообщением.")
        return
    await rasklad_answer(update, context, question)


async def rasklad_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str) -> None:
    user = update.effective_user
    palette = await ensure_palette(update, context)
    if not user or not palette:
        return
    a, b, c = random.sample(RUNES, 3)
    topic = question_type(question)
    context.user_data["last_spread"] = {"question": question, "runes": [a["name"], b["name"], c["name"]], "topic": topic, "palette": palette}
    context.user_data["state"] = STATE_FOLLOWUP
    await thinking(update, context, 1.6)
    text = f"🔮 **Разбираю твой вопрос:**\n«{question}»\n\n**Ситуация — {a['name']}**\n{expanded_text(a, palette, topic, 'situation')}\n\n**Препятствие — {b['name']}**\n{expanded_text(b, palette, topic, 'obstacle')}\n\n**Что поможет — {c['name']}**\n{expanded_text(c, palette, topic, 'advice')}\n\n**Если хочешь уточнить**\nНапиши обычным сообщением, что именно непонятно в раскладе. Я поясню по этим же рунам без нового расклада."
    await send_private(update, context, text, c)


async def followup_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str) -> None:
    data = context.user_data.get("last_spread")
    if not data:
        context.user_data.pop("state", None)
        await context.bot.send_message(update.effective_user.id, "Я не вижу прошлого расклада. Нажми 🔮 Расклад и задай вопрос заново.", reply_markup=MAIN_KEYBOARD)
        return
    await thinking(update, context, 0.9)
    text = f"🜂 **Уточнение по раскладу**\n\nТы спрашиваешь: «{question}»\n\nЯ смотрю не новый расклад, а пояснение к уже выпавшим рунам: {', '.join(data['runes'])}.\n\nПервая руна показывает фон ситуации. Вторая — где застревание. Третья — какой шаг сейчас разумнее. Если что-то непонятно, чаще всего смотри именно на третью руну: она отвечает не “что будет”, а “что делать”."
    context.user_data.pop("state", None)
    await send_private(update, context, text)


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await maybe_redirect_group(update, context):
        return
    if not await ensure_palette(update, context):
        return
    text = (update.effective_message.text or "").strip()
    state = context.user_data.pop("state", None)
    if state == STATE_ASK:
        await one_answer(update, context, text)
        return
    if state == STATE_RASKLAD:
        await rasklad_answer(update, context, text)
        return
    if state == STATE_FOLLOWUP:
        await followup_answer(update, context, text)
        return
    await context.bot.send_message(update.effective_user.id, "Выбери действие ниже.", reply_markup=MAIN_KEYBOARD)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled bot error", exc_info=context.error)


def main() -> None:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not set")
    init_db()
    app = ApplicationBuilder().token(token).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ask", ask_command))
    app.add_handler(CommandHandler("rasklad", rasklad_command))
    app.add_handler(CommandHandler("runa", send_runa_day))
    app.add_handler(CallbackQueryHandler(palette_choice, pattern="^palette_"))
    app.add_handler(CallbackQueryHandler(handle_menu, pattern="^(runa|ask|rasklad)$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.add_error_handler(error_handler)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
