import os
import random
import logging
from datetime import date
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from database import init_db, ensure_user, get_or_create_daily_runes
from runes_data import RUNES, get_rune_by_name

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv('BOT_TOKEN', '').strip()
DB_PATH = os.getenv('DB_PATH', 'rune_bot.db')

STATE_ASK = 'ask'
STATE_RASKLAD = 'rasklad'

MENU = ReplyKeyboardMarkup([
    ['🌞 Руна дня', '❓ Вопрос'],
    ['🔮 Расклад', 'ℹ️ Помощь']
], resize_keyboard=True)


def uname(update: Update) -> str:
    u = update.effective_user
    return (u.first_name or u.username or 'друг') if u else 'друг'


def rune_line(rune: dict, key: str) -> str:
    return rune.get(key) or rune.get('meaning') or rune.get('description') or 'Смысл этой руны пока уточняется.'


def pick_runes(n: int):
    return random.sample(RUNES, min(n, len(RUNES)))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if update.effective_user:
        ensure_user(DB_PATH, update.effective_user.id, uname(update))
    await update.message.reply_text(
        f'🜂 {uname(update)}, бот запущен.\n\nВыбери действие ниже.',
        reply_markup=MENU
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        'ℹ️ Команды:\n\n'
        '🌞 Руна дня — карта на сегодня\n'
        '❓ Вопрос — ответ одной руной\n'
        '🔮 Расклад — ситуация / препятствие / совет\n\n'
        '/runa\n/ask твой вопрос\n/rasklad твой вопрос',
        reply_markup=MENU
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
        f'{rune_line(main, "meaning_situation")}\n\n'
        f'**Дополнительный акцент — {aux["name"]}**\n\n'
        f'{rune_line(aux, "meaning_advice")}\n\n'
        '**Что сделать сегодня**\n'
        'Сделай один конкретный шаг и вернись к меню ниже.'
    )
    await update.message.reply_text(text, reply_markup=MENU, parse_mode='Markdown')


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
        f'**Ответ**\n{rune_line(rune, key)}\n\n'
        '**Что дальше**\n'
        'Проверь вывод на практике и выбери следующее действие в меню.'
    )
    await update.message.reply_text(text, reply_markup=MENU, parse_mode='Markdown')


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
        f'**Ситуация — {a["name"]}**\n{rune_line(a, "meaning_situation")}\n\n'
        f'**Препятствие — {b["name"]}**\n{rune_line(b, "meaning_obstacle")}\n\n'
        f'**Что делать — {c["name"]}**\n{rune_line(c, "meaning_advice")}\n\n'
        'Вернись к меню ниже, чтобы сделать новый запрос.'
    )
    await update.message.reply_text(text, reply_markup=MENU, parse_mode='Markdown')


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
