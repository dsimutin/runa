import os
import random
import logging
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton, InputFile
from telegram.error import Forbidden, BadRequest
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from database import init_db, ensure_user, get_or_create_daily_runes, get_user_profile, start_onboarding, save_onboarding_answer
from runes_data import RUNES, get_rune_by_name
from runes_interpretations import get_interpretation, PSYCHOTYPES

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv('BOT_TOKEN', '').strip()
DB_PATH = os.getenv('DB_PATH', 'rune_bot.db')
PORT = int(os.getenv('PORT', '10000'))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_ASK = 'ask'
STATE_RASKLAD = 'rasklad'

MENU = ReplyKeyboardMarkup([
    ['🌞 Руна дня', '❓ Вопрос'],
    ['🔮 Расклад', 'ℹ️ Помощь']
], resize_keyboard=True)

QUESTIONS = [
    {'text': 'Ты заходишь в незнакомое место. Что замечаешь первым?', 'a': 'Атмосферу: свет, настроение, людей', 'b': 'Структуру: входы, правила, контроль'},
    {'text': 'Когда внутри тревожно, что помогает быстрее?', 'a': 'Тишина, ощущения, мягкий баланс', 'b': 'Назвать проблему и начать действовать'},
    {'text': 'Какой символ тебе ближе прямо сейчас?', 'a': 'Тёплый луч на закрытой двери', 'b': 'Золотой ключ в тёмной комнате'},
]


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'Rune bot is running')
    def log_message(self, *_):
        return


def start_health_server():
    HTTPServer(('0.0.0.0', PORT), HealthHandler).serve_forever()


def uname(update: Update) -> str:
    u = update.effective_user
    return (u.first_name or u.username or 'друг') if u else 'друг'


def is_private(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.type == 'private')


def bot_url(context: ContextTypes.DEFAULT_TYPE) -> str:
    username = context.application.bot_data.get('bot_username') or 'runes2026_bot'
    return f'https://t.me/{username}'


def private_markup(context: ContextTypes.DEFAULT_TYPE):
    return InlineKeyboardMarkup([[InlineKeyboardButton('Открыть личку с ботом', url=bot_url(context))]])


def onboard_keyboard(step: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('A', callback_data=f'onboard:{step}:light')],
        [InlineKeyboardButton('B', callback_data=f'onboard:{step}:dark')],
    ])


def onboard_text(step: int, name: str) -> str:
    q = QUESTIONS[step - 1]
    return f'🜂 {name}, выбери вариант\n\nВопрос {step}/3\n{q["text"]}\n\nA — {q["a"]}\nB — {q["b"]}'


def user_palette(update: Update) -> str:
    try:
        p = get_user_profile(DB_PATH, update.effective_user.id)
        if p and p.get('palette') in ('light', 'dark'):
            return p['palette']
    except Exception:
        logger.exception('profile read failed')
    return os.getenv('RUNE_PALETTE', 'light').strip().lower() or 'light'


def interp(rune: dict, pal: str) -> dict:
    return get_interpretation(rune.get('key', ''), pal, rune)


def line(rune: dict, pal: str, key: str) -> str:
    data = interp(rune, pal)
    return data.get(key) or rune.get(key) or rune.get('short_desc') or 'Смысл этой руны пока уточняется.'


def image_path(rune: dict, pal: str):
    fn = rune.get('image_file')
    if not fn:
        return None
    for folder in [pal, os.path.join('images', pal), os.path.join('decks', pal)]:
        p = os.path.join(BASE_DIR, folder, fn)
        if os.path.exists(p):
            return p
    return None


async def ensure_ready(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.effective_user:
        return False
    if not is_private(update):
        return True
    ensure_user(DB_PATH, update.effective_user.id, uname(update))
    profile = get_user_profile(DB_PATH, update.effective_user.id)
    if profile and profile.get('palette'):
        return True
    start_onboarding(DB_PATH, update.effective_user.id)
    await update.effective_message.reply_text(onboard_text(1, uname(update)), reply_markup=onboard_keyboard(1))
    return False


async def send_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, rune: dict | None = None):
    user = update.effective_user
    msg = update.effective_message
    pal = user_palette(update) if user else 'light'
    path = image_path(rune, pal) if rune else None

    async def send(chat_id):
        if path:
            with open(path, 'rb') as f:
                await context.bot.send_photo(chat_id=chat_id, photo=InputFile(f), caption=text, reply_markup=MENU, parse_mode='Markdown')
        else:
            await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=MENU, parse_mode='Markdown')

    if is_private(update):
        try:
            await send(msg.chat_id)
        except BadRequest:
            await msg.reply_text(text, reply_markup=MENU)
        return

    try:
        await send(user.id)
        await msg.reply_text('Отправил ответ тебе в личку ✨')
    except Forbidden:
        await msg.reply_text('Открой личку с ботом и нажми /start.', reply_markup=private_markup(context))


async def post_init(app: Application):
    await app.bot.delete_webhook(drop_pending_updates=False)
    me = await app.bot.get_me()
    app.bot_data['bot_username'] = me.username


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if not update.effective_user:
        return
    if not is_private(update):
        await update.message.reply_text('Открой личку с ботом и нажми /start.', reply_markup=private_markup(context))
        return
    ensure_user(DB_PATH, update.effective_user.id, uname(update))
    profile = get_user_profile(DB_PATH, update.effective_user.id)
    if not profile or not profile.get('palette'):
        start_onboarding(DB_PATH, update.effective_user.id)
        await update.message.reply_text(onboard_text(1, uname(update)), reply_markup=onboard_keyboard(1))
        return
    await update.message.reply_text(f'🜂 {uname(update)}, бот запущен.\n\nВыбери действие ниже.', reply_markup=MENU)


async def onboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, step_raw, answer = q.data.split(':', 2)
    result = save_onboarding_answer(DB_PATH, update.effective_user.id, answer, len(QUESTIONS))
    if result.get('completed'):
        pal = result['palette']
        profile = PSYCHOTYPES[pal]
        await q.edit_message_text(f'🜂 Колода закреплена\n\nТвоя палитра: {profile["description"]}.')
        await context.bot.send_message(update.effective_user.id, '👇 Выбери действие ниже.', reply_markup=MENU)
        return
    step = result['next_step']
    await q.edit_message_text(onboard_text(step, uname(update)), reply_markup=onboard_keyboard(step))


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await send_answer(update, context, 'ℹ️ **Помощь**\n\n🌞 **Руна дня** — фокус на сегодня.\n❓ **Вопрос** — ответ одной руной.\n🔮 **Расклад** — ситуация / препятствие / что делать.\n\nAI отключён, расходов нет.')


async def runa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if not await ensure_ready(update, context):
        return
    ensure_user(DB_PATH, update.effective_user.id, uname(update))
    main_name, aux_name = get_or_create_daily_runes(DB_PATH, update.effective_user.id, date.today().isoformat(), RUNES)
    pal = user_palette(update)
    main = get_rune_by_name(main_name)
    aux = get_rune_by_name(aux_name)
    text = f'🌞 **Руна дня — {main["name"]}**\n\n{line(main, pal, "short_desc")}\n\n**Дополнительный акцент — {aux["name"]}**\n\n{line(aux, pal, "short_desc")}\n\n**Что сделать сегодня**\nВыбери один конкретный шаг. Меню ниже.'
    await send_answer(update, context, text, main)


async def ask_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_ready(update, context):
        return
    question = ' '.join(context.args).strip()
    if not question:
        context.user_data['state'] = STATE_ASK
        await update.effective_message.reply_text('❓ Напиши вопрос следующим сообщением.', reply_markup=MENU)
        return
    await one_answer(update, context, question)


async def one_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str):
    context.user_data.pop('state', None)
    pal = user_palette(update)
    rune = random.choice(RUNES)
    key = 'answer_yes' if random.random() < 0.5 else 'answer_no'
    text = f'❓ **Вопрос:** {question}\n\n**Карта — {rune["name"]}**\n\n**Ответ**\n{line(rune, pal, key)}\n\n**Что дальше**\nПроверь вывод действием. Меню ниже.'
    await send_answer(update, context, text, rune)


async def rasklad_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_ready(update, context):
        return
    question = ' '.join(context.args).strip()
    if not question:
        context.user_data['state'] = STATE_RASKLAD
        await update.effective_message.reply_text('🔮 Напиши вопрос для расклада следующим сообщением.', reply_markup=MENU)
        return
    await rasklad_answer(update, context, question)


async def rasklad_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str):
    context.user_data.pop('state', None)
    pal = user_palette(update)
    a, b, c = random.sample(RUNES, 3)
    text = f'🔮 **Расклад на вопрос:** {question}\n\n**Ситуация — {a["name"]}**\n{line(a, pal, "situation")}\n\n**Препятствие — {b["name"]}**\n{line(b, pal, "obstacle")}\n\n**Что делать — {c["name"]}**\n{line(c, pal, "advice")}\n\nМеню ниже — можно сделать новый запрос.'
    await send_answer(update, context, text, c)


async def check_decks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = ['🧩 **Проверка колод**']
    for pal in ['light', 'dark']:
        found = sum(1 for r in RUNES if image_path(r, pal))
        rows.append(f'{pal}: {found}/{len(RUNES)}')
    await send_answer(update, context, '\n'.join(rows))


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_ready(update, context):
        return
    text = (update.effective_message.text or '').strip()
    if text == '🌞 Руна дня':
        await runa(update, context); return
    if text == '❓ Вопрос':
        context.user_data['state'] = STATE_ASK
        await update.effective_message.reply_text('❓ Напиши вопрос следующим сообщением.', reply_markup=MENU); return
    if text == '🔮 Расклад':
        context.user_data['state'] = STATE_RASKLAD
        await update.effective_message.reply_text('🔮 Напиши вопрос для расклада следующим сообщением.', reply_markup=MENU); return
    if text == 'ℹ️ Помощь':
        await help_cmd(update, context); return
    state = context.user_data.pop('state', None)
    if state == STATE_ASK:
        await one_answer(update, context, text); return
    if state == STATE_RASKLAD:
        await rasklad_answer(update, context, text); return
    await update.effective_message.reply_text('Выбери действие кнопкой ниже.', reply_markup=MENU)


def main():
    if not BOT_TOKEN:
        raise RuntimeError('BOT_TOKEN is not set')
    init_db(DB_PATH)
    threading.Thread(target=start_health_server, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_cmd))
    app.add_handler(CommandHandler('runa', runa))
    app.add_handler(CommandHandler('ask', ask_cmd))
    app.add_handler(CommandHandler('rasklad', rasklad_cmd))
    app.add_handler(CommandHandler('check_decks', check_decks))
    app.add_handler(CallbackQueryHandler(onboard, pattern='^onboard:'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
