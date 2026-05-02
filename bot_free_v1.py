import os
import random
import logging
from datetime import date
from telegram import Update, ReplyKeyboardMarkup, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from database import init_db, ensure_user, get_or_create_daily_runes
from runes_data import RUNES, get_rune_by_name
from runes_interpretations import get_interpretation

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv('BOT_TOKEN', '').strip()
DB_PATH = os.getenv('DB_PATH', 'rune_bot.db')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_ASK = 'ask'
STATE_RASKLAD = 'rasklad'

MENU = ReplyKeyboardMarkup([
    ['🌞 Руна дня', '❓ Вопрос'],
    ['🔮 Расклад', 'ℹ️ Помощь']
], resize_keyboard=True)


def uname(update: Update) -> str:
    u = update.effective_user
    return (u.first_name or u.username or 'друг') if u else 'друг'


def palette() -> str:
    return os.getenv('RUNE_PALETTE', 'light').strip().lower() or 'light'


def interp(rune: dict) -> dict:
    return get_interpretation(rune.get('key', ''), palette(), rune)


def line(rune: dict, key: str) -> str:
    data = interp(rune)
    return data.get(key) or rune.get(key) or rune.get('short_desc') or 'Смысл этой руны пока уточняется.'


def image_path(rune: dict):
    file_name = rune.get('image_file')
    if not file_name:
        return None
    for folder in [palette(), os.path.join('images', palette()), os.path.join('decks', palette())]:
        p = os.path.join(BASE_DIR, folder, file_name)
        if os.path.exists(p):
            return p
    return None


async def send_answer(update: Update, text: str, rune: dict | None = None):
    path = image_path(rune) if rune else None
    if path:
        with open(path, 'rb') as f:
            await update.message.reply_photo(photo=InputFile(f), caption=text, reply_markup=MENU, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=MENU, parse_mode='Markdown')


def pick_runes(n: int):
    return random.sample(RUNES, min(n, len(RUNES)))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if update.effective_user:
        ensure_user(DB_PATH, update.effective_user.id, uname(update))
    await update.message.reply_text(
        f'🜂 {uname(update)}, бот запущен.\n\n'
        'Это бесплатная версия без AI-запросов. Все ответы берутся из готовых интерпретаций.\n\n'
        'Выбери действие ниже.',
        reply_markup=MENU
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        'ℹ️ **Помощь**\n\n'
        '🌞 **Руна дня** — фокус и дополнительный акцент на сегодня.\n'
        '❓ **Вопрос** — быстрый ответ одной руной.\n'
        '🔮 **Расклад** — три блока: ситуация, препятствие, что делать.\n\n'
        'AI отключён, расходов нет.\n\n'
        '/runa\n/ask твой вопрос\n/rasklad твой вопрос',
        reply_markup=MENU,
        parse_mode='Markdown'
    )


async def runa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if not update.effective_user:
        return
    ensure_user(DB_PATH, update.effective_user.id, uname(update))
    today = date.today().isoformat()
    main_name, aux_name = get_or_create_daily_runes(DB_PATH, update.effective_user.id, today, RUNES)
    main = get_rune_by_name(main_name)
    aux = get_rune_by_name(aux_name)
    text = (
        f'🌞 **Руна дня — {main["name"]}**\n\n'
        f'{line(main, "short_desc")}\n\n'
        f'**Дополнительный акцент — {aux["name"]}**\n\n'
        f'{line(aux, "short_desc")}\n\n'
        '**Что сделать сегодня**\n'
        'Выбери один конкретный шаг. Не распыляйся. Меню уже ниже.'
    )
    await send_answer(update, text, main)


async def ask_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    question = ' '.join(context.args).strip()
    if not question:
        context.user_data['state'] = STATE_ASK
        await update.message.reply_text('❓ Напиши вопрос следующим сообщением.', reply_markup=MENU)
        return
    await one_rune_answer(update, context, question)


async def one_rune_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str):
    context.user_data.pop('state', None)
    rune = random.choice(RUNES)
    positive = random.random() < 0.5
    key = 'answer_yes' if positive else 'answer_no'
    label = 'совет' if positive else 'предупреждение'
    text = (
        f'❓ **Вопрос:** {question}\n\n'
        f'**Карта — {rune["name"]}**\n'
        f'Формат: {label}\n\n'
        f'**Ответ**\n{line(rune, key)}\n\n'
        '**Что дальше**\n'
        'Проверь вывод действием и выбери следующий шаг в меню.'
    )
    await send_answer(update, text, rune)


async def rasklad_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    question = ' '.join(context.args).strip()
    if not question:
        context.user_data['state'] = STATE_RASKLAD
        await update.message.reply_text('🔮 Напиши вопрос для расклада следующим сообщением.', reply_markup=MENU)
        return
    await rasklad_answer(update, context, question)


async def rasklad_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str):
    context.user_data.pop('state', None)
    a, b, c = pick_runes(3)
    text = (
        f'🔮 **Расклад на вопрос:** {question}\n\n'
        f'**Ситуация — {a["name"]}**\n{line(a, "situation")}\n\n'
        f'**Препятствие — {b["name"]}**\n{line(b, "obstacle")}\n\n'
        f'**Что делать — {c["name"]}**\n{line(c, "advice")}\n\n'
        'Меню ниже — можно сделать новый запрос.'
    )
    await send_answer(update, text, c)


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or '').strip()
    if text == '🌞 Руна дня':
        await runa(update, context)
        return
    if text == '❓ Вопрос':
        context.user_data['state'] = STATE_ASK
        await update.message.reply_text('❓ Напиши вопрос следующим сообщением.', reply_markup=MENU)
        return
    if text == '🔮 Расклад':
        context.user_data['state'] = STATE_RASKLAD
        await update.message.reply_text('🔮 Напиши вопрос для расклада следующим сообщением.', reply_markup=MENU)
        return
    if text == 'ℹ️ Помощь':
        await help_cmd(update, context)
        return

    state = context.user_data.pop('state', None)
    if state == STATE_ASK:
        await one_rune_answer(update, context, text)
        return
    if state == STATE_RASKLAD:
        await rasklad_answer(update, context, text)
        return

    await update.message.reply_text('Выбери действие кнопкой ниже.', reply_markup=MENU)


def main():
    if not BOT_TOKEN:
        raise RuntimeError('BOT_TOKEN is not set')
    init_db(DB_PATH)
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_cmd))
    app.add_handler(CommandHandler('runa', runa))
    app.add_handler(CommandHandler('ask', ask_cmd))
    app.add_handler(CommandHandler('rasklad', rasklad_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
