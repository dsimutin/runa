import logging
import os
import random
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List

from dotenv import load_dotenv
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
from runes_interpretations import PSYCHOTYPES, get_interpretation

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
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DECK_DIRS = {"light": "light", "dark": "dark"}

STATE_WAITING_ASK = "waiting_ask"
STATE_WAITING_RASKLAD = "waiting_rasklad"

ONBOARDING_QUESTIONS = [
    {"text": "Ты заходишь в незнакомое место. Что замечаешь первым?", "a": "Атмосферу: свет, воздух, настроение, людей", "b": "Структуру: входы, выходы, правила, кто контролирует пространство"},
    {"text": "Когда внутри тревожно, что помогает быстрее?", "a": "Побыть в тишине, собрать ощущения, мягко вернуть себя в баланс", "b": "Назвать проблему прямо, принять решение и начать действовать"},
    {"text": "Какой символ тебе ближе прямо сейчас?", "a": "Тёплый луч на закрытой двери", "b": "Золотой ключ в тёмной комнате"},
]

logging.basicConfig(format="%(asctime)s | %(name)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

MAIN_KEYBOARD = ReplyKeyboardMarkup([["🌞 Руна дня", "❓ Вопрос"], ["🔮 Расклад", "ℹ️ Помощь"]], resize_keyboard=True)


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
    logger.info("%s | user_id=%s username=%s chat_id=%s chat_type=%s text=%r", action, user.id if user else None, user.username if user else None, chat.id if chat else None, chat.type if chat else None, message.text if message else None)


def choose_distinct_runes(count: int) -> List[Dict[str, Any]]:
    return random.sample(RUNES, min(count, len(RUNES)))


def bot_link(context: ContextTypes.DEFAULT_TYPE) -> str:
    username = context.application.bot_data.get("bot_username") or "runes2026_bot"
    return f"https://t.me/{username}"


def private_link_markup(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Открыть личку с ботом", url=bot_link(context))]])


def onboarding_keyboard(step: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("A", callback_data=f"onboarding:{step}:light")], [InlineKeyboardButton("B", callback_data=f"onboarding:{step}:dark")]])


def build_onboarding_question(step: int, name: str) -> str:
    question = ONBOARDING_QUESTIONS[step - 1]
    return f"🜂 {name}, выбери вариант\n\nВопрос {step}/3\n{question['text']}\n\nA — {question['a']}\nB — {question['b']}"


def onboarding_result_text(palette: str) -> str:
    profile = PSYCHOTYPES[palette]
    return f"🜂 Колода закреплена\n\nТвоя палитра: {profile['description']}.\n\nСтиль чтения: {profile['reading_style']}.\n\nТеперь можно выбрать действие ниже."


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


def rune_text(rune: Dict[str, Any], palette: str) -> Dict[str, str]:
    return get_interpretation(rune.get("key", ""), palette, rune)


def get_rune_image_path(rune: Dict[str, Any], palette: str) -> str | None:
    image_file = rune.get("image_file")
    if not image_file:
        return None
    deck_dir = DECK_DIRS.get(palette, "light")
    candidates = [os.path.join(BASE_DIR, deck_dir, image_file), os.path.join(BASE_DIR, "decks", deck_dir, image_file)]
    for path in candidates:
        if os.path.exists(path):
            return path
    logger.warning("Rune image not found: palette=%s file=%s", palette, image_file)
    return None


def rune_input_file(rune: Dict[str, Any], palette: str) -> InputFile | None:
    path = get_rune_image_path(rune, palette)
    if not path:
        return None
    return InputFile(open(path, "rb"), filename=rune.get("image_file", "rune.jpg"))


def check_deck_files() -> Dict[str, List[str]]:
    missing: Dict[str, List[str]] = {}
    for palette in ("light", "dark"):
        missing[palette] = []
        for rune in RUNES:
            if not get_rune_image_path(rune, palette):
                missing[palette].append(rune.get("image_file", rune.get("name", "unknown")))
    return missing


def format_daily_message(name: str, main_rune: Dict[str, Any], main_text: Dict[str, str], aux_rune: Dict[str, Any], aux_text: Dict[str, str]) -> str:
    return (
        f"🌞 {name}, руна дня\n\n"
        f"Основная карта — {main_rune['name']}\n"
        f"{main_text['short_desc']}\n\n"
        f"Дополнительный акцент — {aux_rune['name']}\n"
        f"{aux_text['short_desc']}\n\n"
        f"Что сделать сегодня\n"
        f"Выбери один конкретный шаг по основной карте. Дополнительная руна показывает, где не стоит действовать на автомате."
    )


def format_one_rune_answer(name: str, question: str, rune: Dict[str, Any], answer: str, label: str) -> str:
    return (
        f"❓ {name}, ответ\n\n"
        f"Вопрос: {question}\n\n"
        f"Карта — {rune['name']}\n"
        f"Формат — {label}\n\n"
        f"Ответ\n"
        f"{answer}\n\n"
        f"Практический вывод\n"
        f"Используй карту как подсказку: что проверить, где остановиться и какой шаг сделать трезво."
    )


async def ensure_profile_ready(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    message = update.effective_message
    if not user or not message:
        return False
    if not is_private(update):
        return True
    try:
        ensure_user(DB_PATH, user.id, user_name(update))
        profile = get_user_profile(DB_PATH, user.id)
        if profile and profile.get("palette"):
            return True
        step = profile.get("onboarding_step", 0) if profile else 0
        if step <= 0:
            start_onboarding(DB_PATH, user.id)
            step = 1
        await message.reply_text(build_onboarding_question(step, user_name(update)), reply_markup=onboarding_keyboard(step))
        return False
    except DatabaseError:
        logger.exception("Failed to prepare user profile")
        await message.reply_text("Не получилось настроить профиль. Попробуй позже.")
        return False


async def send_private_or_group(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, *, image: InputFile | None = None) -> None:
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return
    if is_private(update):
        if image:
            await message.reply_photo(photo=image, caption=text, reply_markup=MAIN_KEYBOARD)
        else:
            await message.reply_text(text, reply_markup=MAIN_KEYBOARD)
        return
    try:
        if image:
            await context.bot.send_photo(chat_id=user.id, photo=image, caption=text)
        else:
            await context.bot.send_message(chat_id=user.id, text=text)
        await message.reply_text("Отправил ответ тебе в личку ✨")
    except Forbidden:
        await message.reply_text("Открой личку с ботом и нажми /start, тогда я смогу отправлять личные ответы.", reply_markup=private_link_markup(context))


def short_help() -> str:
    return (
        "ℹ️ Помощь\n\n"
        "🌞 /runa — руна дня\n"
        "❓ /ask <вопрос> — ответ одной картой\n"
        "🔮 /rasklad <вопрос> — расклад на 3 карты\n"
        "🜂 /profile — твоя колода\n"
        "🧩 /check_decks — проверка файлов"
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /start")
    context.user_data.clear()
    name = user_name(update)
    if not is_private(update):
        await update.effective_message.reply_text("Открой личку с ботом. В группе я отправляю личные ответы только после /start.", reply_markup=private_link_markup(context))
        return
    try:
        ensure_user(DB_PATH, update.effective_user.id, name)
        profile = get_user_profile(DB_PATH, update.effective_user.id)
        if not profile or not profile.get("palette"):
            start_onboarding(DB_PATH, update.effective_user.id)
            await update.effective_message.reply_text(build_onboarding_question(1, name), reply_markup=onboarding_keyboard(1))
            return
    except DatabaseError:
        logger.exception("Failed to start onboarding")
        await update.effective_message.reply_text("Не получилось настроить профиль. Попробуй позже.")
        return
    await update.effective_message.reply_text(f"🜂 {name}, колода уже закреплена\n\nВыбери действие ниже.", reply_markup=MAIN_KEYBOARD)


async def onboarding_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user:
        return
    await query.answer()
    try:
        _, step_raw, answer = query.data.split(":", 2)
        step = int(step_raw)
    except (ValueError, AttributeError):
        await query.edit_message_text("Не удалось прочитать ответ. Нажми /start и попробуй снова.")
        return
    try:
        result = save_onboarding_answer(DB_PATH, update.effective_user.id, answer, len(ONBOARDING_QUESTIONS))
    except DatabaseError:
        logger.exception("Failed to save onboarding answer")
        await query.edit_message_text("Не получилось сохранить ответ. Попробуй позже.")
        return
    if result.get("completed"):
        await query.edit_message_text(onboarding_result_text(result["palette"]))
        await context.bot.send_message(chat_id=update.effective_user.id, text="Выбери действие:", reply_markup=MAIN_KEYBOARD)
        return
    next_step = result["next_step"]
    await query.edit_message_text(build_onboarding_question(next_step, user_name(update)), reply_markup=onboarding_keyboard(next_step))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /help")
    context.user_data.clear()
    if not await ensure_profile_ready(update, context):
        return
    await send_private_or_group(update, context, short_help())


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /profile")
    if not await ensure_profile_ready(update, context):
        return
    palette = get_user_palette(update)
    profile = PSYCHOTYPES[palette]
    text = (
        "🜂 Твой профиль\n\n"
        f"Колода: {'светлая' if palette == 'light' else 'тёмная'}\n"
        f"Стиль: {profile['name']}\n\n"
        f"Как читается:\n{profile['reading_style']}.\n\n"
        "Сброс: удалить чат с ботом и начать заново."
    )
    await send_private_or_group(update, context, text)


async def check_decks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /check_decks")
    missing = check_deck_files()
    lines = ["🧩 Проверка колод", ""]
    for palette in ("light", "dark"):
        count = len(RUNES) - len(missing[palette])
        title = "светлая" if palette == "light" else "тёмная"
        lines.append(f"{title}: {count}/{len(RUNES)}")
        if missing[palette]:
            lines.append("Не найдены:")
            lines.extend(f"— {name}" for name in missing[palette])
        lines.append("")
    await send_private_or_group(update, context, "\n".join(lines).strip())


async def send_missing_image_error(update: Update, context: ContextTypes.DEFAULT_TYPE, rune: Dict[str, Any], palette: str) -> None:
    await send_private_or_group(update, context, f"Не найдена карта {rune.get('image_file', rune.get('name', ''))} в папке {palette}. Проверь /check_decks.")


async def runa_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /runa")
    context.user_data.clear()
    if not update.effective_user:
        return
    if not await ensure_profile_ready(update, context):
        return
    today = date.today().isoformat()
    try:
        main_name, aux_name = get_or_create_daily_runes(DB_PATH, update.effective_user.id, today, RUNES)
    except DatabaseError:
        logger.exception("Failed to get daily runes")
        await send_private_or_group(update, context, "Не получилось достать руну дня. Попробуй позже.")
        return
    palette = get_user_palette(update)
    main_rune = get_rune_by_name(main_name)
    aux_rune = get_rune_by_name(aux_name)
    image = rune_input_file(main_rune, palette)
    if not image:
        await send_missing_image_error(update, context, main_rune, palette)
        return
    text = format_daily_message(user_name(update), main_rune, rune_text(main_rune, palette), aux_rune, rune_text(aux_rune, palette))
    await send_private_or_group(update, context, text, image=image)


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /ask")
    if not await ensure_profile_ready(update, context):
        return
    question = " ".join(context.args).strip()
    if not question:
        context.user_data["state"] = STATE_WAITING_ASK
        await update.effective_message.reply_text("❓ Напиши вопрос следующим сообщением.", reply_markup=MAIN_KEYBOARD if is_private(update) else None)
        return
    await send_one_rune_answer(update, context, question)


async def send_one_rune_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str) -> None:
    if not await ensure_profile_ready(update, context):
        return
    palette = get_user_palette(update)
    rune = random.choice(RUNES)
    image = rune_input_file(rune, palette)
    if not image:
        await send_missing_image_error(update, context, rune, palette)
        return
    text_data = rune_text(rune, palette)
    is_yes = random.random() < 0.5
    label = "совет" if is_yes else "предупреждение"
    answer = text_data["answer_yes"] if is_yes else text_data["answer_no"]
    text = format_one_rune_answer(user_name(update), question, rune, answer, label)
    await send_private_or_group(update, context, text, image=image)


def build_template_rasklad(name: str, question: str, runes: List[Dict[str, Any]], palette: str) -> str:
    return generate_rasklad(runes, question, palette, name)


def build_gpt_prompt(name: str, question: str, runes: List[Dict[str, Any]]) -> str:
    return f"Ты пишешь короткий трёхрунный расклад на русском языке до 300 символов. Не обещай гарантированный результат.\nИмя: {name}\nВопрос: {question}\nСитуация: {runes[0]['name']} — {runes[0]['meaning_situation']}\nПрепятствие: {runes[1]['name']} — {runes[1]['meaning_obstacle']}\nСовет: {runes[2]['name']} — {runes[2]['meaning_advice']}"


async def build_ai_rasklad(name: str, question: str, runes: List[Dict[str, Any]]) -> str:
    if not OPENAI_API_KEY or OpenAI is None:
        return "Функция расклада с AI временно недоступна, используйте /ask или /runa."
    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(model=OPENAI_MODEL, messages=[{"role": "system", "content": "Ты помощник для рунических раскладов. Пиши кратко и без категоричных обещаний."}, {"role": "user", "content": build_gpt_prompt(name, question, runes)}], max_tokens=120, temperature=0.8)
    return response.choices[0].message.content.strip()


async def rasklad_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /rasklad")
    if not await ensure_profile_ready(update, context):
        return
    question = " ".join(context.args).strip()
    if not question:
        context.user_data["state"] = STATE_WAITING_RASKLAD
        await update.effective_message.reply_text("🔮 Напиши вопрос для расклада следующим сообщением.", reply_markup=MAIN_KEYBOARD if is_private(update) else None)
        return
    await send_rasklad(update, context, question)


async def send_rasklad(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str) -> None:
    if not await ensure_profile_ready(update, context):
        return
    name = user_name(update)
    runes = choose_distinct_runes(3)
    palette = get_user_palette(update)
    image = rune_input_file(runes[2], palette)
    if not image:
        await send_missing_image_error(update, context, runes[2], palette)
        return
    try:
        text = await build_ai_rasklad(name, question, runes) if USE_GPT else build_template_rasklad(name, question, runes, palette)
    except Exception:
        logger.exception("Failed to build rasklad")
        await send_private_or_group(update, context, "Не получилось сделать расклад. Попробуй позже.")
        return
    await send_private_or_group(update, context, text, image=image)


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received text")
    text = (update.effective_message.text or "").strip()
    if not await ensure_profile_ready(update, context):
        return
    if text == "🌞 Руна дня":
        await runa_command(update, context)
        return
    if text in {"❓ Вопрос", "❓ Задать вопрос"}:
        context.user_data["state"] = STATE_WAITING_ASK
        await update.effective_message.reply_text("❓ Напиши вопрос следующим сообщением.", reply_markup=MAIN_KEYBOARD if is_private(update) else None)
        return
    if text == "🔮 Расклад":
        context.user_data["state"] = STATE_WAITING_RASKLAD
        await update.effective_message.reply_text("🔮 Напиши вопрос для расклада следующим сообщением.", reply_markup=MAIN_KEYBOARD if is_private(update) else None)
        return
    if text == "ℹ️ Помощь":
        await help_command(update, context)
        return
    state = context.user_data.get("state")
    context.user_data.pop("state", None)
    if state == STATE_WAITING_ASK:
        await send_one_rune_answer(update, context, text)
        return
    if state == STATE_WAITING_RASKLAD:
        await send_rasklad(update, context, text)
        return
    await update.effective_message.reply_text("Выбери действие кнопкой ниже или напиши /help.", reply_markup=MAIN_KEYBOARD if is_private(update) else private_link_markup(context))


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled bot error", exc_info=context.error)


def build_application() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set. Add it in Render Environment variables.")
    init_db(DB_PATH)
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("check_decks", check_decks_command))
    app.add_handler(CommandHandler("runa", runa_command))
    app.add_handler(CommandHandler("ask", ask_command))
    app.add_handler(CommandHandler("rasklad", rasklad_command))
    app.add_handler(CallbackQueryHandler(onboarding_callback, pattern=r"^onboarding:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.add_error_handler(error_handler)
    return app


def main() -> None:
    start_health_server()
    app = build_application()
    logger.info("Starting bot in polling mode")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False, close_loop=False)


if __name__ == "__main__":
    main()
