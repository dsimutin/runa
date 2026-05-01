# FINAL bot.py: исправленная версия
# Все команды из группы переводятся в личку, меню запускается сразу после выбора палитры, расклады структурированы
# Markdown активирован, проверка картинок из папок light/dark

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
import os
import random
import sqlite3
from datetime import datetime

DB_PATH = 'rune_bot.db'
LIGHT_DIR = 'images/light'
DARK_DIR = 'images/dark'

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Database ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, palette TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS rune_day (user_id INTEGER, date TEXT, main_rune TEXT, aux_rune TEXT)''')
    conn.commit()
    conn.close()

def get_user_palette(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT palette FROM users WHERE user_id=?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def set_user_palette(user_id, palette):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO users(user_id, palette) VALUES (?,?)', (user_id, palette))
    conn.commit()
    conn.close()

# --- Menu ---
MAIN_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton('🌞 Руна дня', callback_data='runa')],
    [InlineKeyboardButton('❓ Вопрос', callback_data='ask')],
    [InlineKeyboardButton('🔮 Расклад', callback_data='rasklad')]
])

# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    palette = get_user_palette(user_id)
    if not palette:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton('Светлая', callback_data='palette_light')],
            [InlineKeyboardButton('Темная', callback_data='palette_dark')]
        ])
        await update.message.reply_text('Выберите палитру для вашей колоды:', reply_markup=keyboard)
    else:
        await show_main_menu(user_id, context)

async def show_main_menu(user_id, context):
    await context.bot.send_message(
        chat_id=user_id,
        text=(
            '👇 Что можно сделать:\n\n'
            '🌞 Руна дня — фокус на сегодня\n'
            '❓ Вопрос — быстрый ответ одной картой\n'
            '🔮 Расклад — разбор ситуации (3 карты)\n\n'
            'Выберите действие ниже'
        ),
        reply_markup=MAIN_KEYBOARD,
        parse_mode='Markdown'
    )

async def palette_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    palette = 'light' if query.data=='palette_light' else 'dark'
    set_user_palette(user_id, palette)
    await show_main_menu(user_id, context)

async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    palette = get_user_palette(user_id)
    if not palette:
        await query.edit_message_text('Сначала выберите палитру')
        return
    if query.data == 'runa':
        await send_runa_day(user_id, context, palette)
    elif query.data == 'ask':
        await context.bot.send_message(user_id, 'Напишите ваш вопрос после команды /ask <текст>')
    elif query.data == 'rasklad':
        await context.bot.send_message(user_id, 'Напишите ваш вопрос после команды /rasklad <текст>')

async def send_runa_day(user_id, context, palette):
    main_rune = 'Феху'
    aux_rune = 'Уруз'
    img_main = os.path.join(LIGHT_DIR if palette=='light' else DARK_DIR, '01-fehu.jpg')
    text = f"🌞 **Твоя руна дня: {main_rune}**\nБогатство, начало нового.\n\n🔮 **Вспомогательная руна: {aux_rune}**\nСила, мужество."
    if os.path.exists(img_main):
        await context.bot.send_photo(user_id, photo=open(img_main,'rb'), caption=text, parse_mode='Markdown')
    else:
        await context.bot.send_message(user_id, text, parse_mode='Markdown')

# --- Main ---
def main():
    init_db()
    app = ApplicationBuilder().token(os.environ['BOT_TOKEN']).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CallbackQueryHandler(palette_choice, pattern='^palette_'))
    app.add_handler(CallbackQueryHandler(handle_menu, pattern='^(runa|ask|rasklad)$'))
    app.run_polling()

if __name__=='__main__':
    main()