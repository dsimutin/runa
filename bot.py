import os
import random
import hashlib
from datetime import date
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from runes_data import RUNES, get_rune_by_name
from runes_interpretations import get_interpretation
from database import init_db, ensure_user, get_user_profile, get_or_create_daily_runes

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "rune_bot.db")

KEYBOARD = ReplyKeyboardMarkup([
    ["🌞 Руна дня", "❓ Вопрос"],
    ["🔮 Расклад"]
], resize_keyboard=True)

ALT_RATE = 0.3


def alt_state(user_id, rune_key):
    raw = f"{user_id}:{rune_key}".encode()
    val = int(hashlib.sha256(raw).hexdigest()[:8], 16) / 0xFFFFFFFF
    return val < ALT_RATE


def format_daily(name, rune, text, alt):
    title = rune["name"] + (" (обратное)" if alt else "")
    desc = text["short_desc"]

    return (
        f"🌞 {name}\n\n"
        f"Фокус: {title}\n\n"
        f"{desc}\n\n"
        f"Действие:\n"
        f"Сфокусируйся на одном шаге."
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(DB_PATH, user.id, user.first_name)
    await update.message.reply_text("Бот готов", reply_markup=KEYBOARD)


async def runa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = user.first_name

    main, aux = get_or_create_daily_runes(DB_PATH, user.id, date.today().isoformat(), RUNES)
    rune = get_rune_by_name(main)

    text = get_interpretation(rune["key"], "light", rune)
    alt = alt_state(user.id, rune["key"])

    msg = format_daily(name, rune, text, alt)
    await update.message.reply_text(msg)


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "🌞 Руна дня":
        await runa(update, context)



def main():
    init_db(DB_PATH)
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("runa", runa))
    app.add_handler(MessageHandler(filters.TEXT, text_router))

    app.run_polling()


if __name__ == "__main__":
    main()
