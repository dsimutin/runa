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
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from database import (
    DatabaseError,
    ensure_user,
    get_or_create_daily_runes,
    get_user_profile,
    init_db,
    save_onboarding_answer,
    start_onboarding,
)
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


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def make_rune_card(rune_name: str, subtitle: str = "") -> io.BytesIO:
    symbol = RUNE_SYMBOLS.get(rune_name, "ᚱ")
    width, height = 900, 900
    img = Image.new("RGB", (width, height), (32, 36, 32))
    draw = ImageDraw.Draw(img)

    for y in range(height):
        ratio = y / height
        r = int(43 + 56 * ratio)
        g = int(49 + 37 * ratio)
        b = int(43 + 28 * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    draw.ellipse((95, 95, 805, 805), outline=(196, 174, 127), width=6)
    draw.ellipse((145, 145, 755, 755), outline=(103, 126, 86), width=3)

    symbol_font = load_font(290)
    name_font = load_font(58)
    subtitle_font = load_font(34)

    def centered_text(text: str, y: int, font: ImageFont.ImageFont, fill: Tuple[int, int, int]) -> None:
        box = draw.textbbox((0, 0), text, font=font)
        x = (width - (box[2] - box[0])) // 2
        draw.text((x, y), text, font=font, fill=fill)

    centered_text(symbol, 210, symbol_font, (238, 218, 169))
    centered_text(rune_name, 610, name_font, (246, 239, 221))
    if subtitle:
        centered_text(subtitle, 690, subtitle_font, (191, 202, 174))

    output = io.BytesIO()
    output.name = f"{rune_name}.png"
    img.save(output, format="PNG")
    output.seek(0)
    return output


async def send_private_or_group(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, *, image: io.BytesIO | None = None) -> None:
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    if is_private(update):
        if image:
            await message.reply_photo(photo=InputFile(image), caption=text, reply_markup=MAIN_KEYBOARD)
        else:
            await message.reply_text(text, reply_markup=MAIN_KEYBOARD)
        return

    try:
        if image:
            await context.bot.send_photo(chat_id=user.id, photo=InputFile(image), caption=text)
        else:
            await context.bot.send_message(chat_id=user.id, text=text)
        await message.reply_text("Отправил ответ тебе в личку ✨")
    except Forbidden:
        await message.reply_text(
            "Я могу отправить личный ответ, но сначала открой чат со мной и нажми /start.",
            reply_markup=private_link_markup(context),
        )


def short_help() -> str:
    return (
        "Выбери действие кнопкой или напиши команду:\n\n"
        "🌞 /runa — руна дня\n"
        "❓ /ask <вопрос> — ответ одной руной\n"
        "🔮 /rasklad <вопрос> — расклад на 3 руны"
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /start")
    context.user_data.clear()
    name = user_name(update)

    if not is_private(update):
        await update.effective_message.reply_text(
            "Чтобы ответы видел только ты, открой личку с ботом. В группе я буду отправлять расклады в личные сообщения.",
            reply_markup=private_link_markup(context),
        )
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

    text = f"Привет, {name} ✨\n\nТвоя колода уже настроена. Выбери действие ниже."
    await update.effective_message.reply_text(text, reply_markup=MAIN_KEYBOARD)


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

    main_rune = get_rune_by_name(main_name)
    aux_rune = get_rune_by_name(aux_name)
    name = user_name(update)
    text = (
        f"🌞 {name}, руна дня — {main_rune['name']}\n\n"
        f"{main_rune['short_desc']}\n\n"
        f"🔮 Дополнительная энергия — {aux_rune['name']}\n"
        f"{aux_rune['short_desc']}"
    )
    await send_private_or_group(update, context, text, image=make_rune_card(main_rune["name"], "Руна дня"))


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_update(update, "Received /ask")
    if not await ensure_profile_ready(update, context):
        return
    question = " ".join(context.args).strip()
    if not question:
        context.user_data["state"] = STATE_WAITING_ASK
        await update.effective_message.reply_text("Напиши вопрос следующим сообщением.", reply_markup=MAIN_KEYBOARD if is_private(update) else None)
        return
    await send_one_rune_answer(update, context, question)


async def send_one_rune_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str) -> None:
    if not await ensure_profile_ready(update, context):
        return
    rune = random.choice(RUNES)
    is_yes = random.random() < 0.5
    answer = rune["answer_yes"] if is_yes else rune["answer_no"]
    label = "совет" if is_yes else "предупреждение"
    name = user_name(update)

    text = (
        f"❓ {name}, вопрос:\n{question}\n\n"
        f"ᚱ Руна — {rune['name']}\n"
        f"Тип: {label}\n\n"
        f"{answer}"
    )
    await send_private_or_group(update, context, text, image=make_rune_card(rune["name"], "Ответ"))


def build_template_rasklad(name: str, question: str, runes: List[Dict[str, Any]]) -> str:
    situation, obstacle, advice = runes
    return (
        f"🔮 {name}, расклад:\n{question}\n\n"
        f"1. Ситуация — {situation['name']}\n{situation['meaning_situation']}\n\n"
        f"2. Препятствие — {obstacle['name']}\n{obstacle['meaning_obstacle']}\n\n"
        f"3. Совет — {advice['name']}\n{advice['meaning_advice']}\n\n"
        f"Итог: главный ключ — {advice['name']}. Действуй точнее, не из напряжения."
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
    if not await ensure_profile_ready(update, context):
        return
    question = " ".join(context.args).strip()
    if not question:
        context.user_data["state"] = STATE_WAITING_RASKLAD
        await update.effective_message.reply_text("Напиши вопрос следующим сообщением.", reply_markup=MAIN_KEYBOARD if is_private(update) else None)
        return
    await send_rasklad(update, context, question)


async def send_rasklad(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str) -> None:
    if not await ensure_profile_ready(update, context):
        return
    name = user_name(update)
    runes = choose_distinct_runes(3)

    try:
        text = await build_ai_rasklad(name, question, runes) if USE_GPT else build_template_rasklad(name, question, runes)
    except Exception:
        logger.exception("Failed to build rasklad")
        await send_private_or_group(update, context, "Не получилось сделать расклад. Попробуй позже.")
        return

    await send_private_or_group(update, context, text, image=make_rune_card(runes[2]["name"], "Совет расклада"))


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
        await update.effective_message.reply_text("Напиши вопрос следующим сообщением.", reply_markup=MAIN_KEYBOARD if is_private(update) else None)
        return
    if text == "🔮 Расклад":
        context.user_data["state"] = STATE_WAITING_RASKLAD
        await update.effective_message.reply_text("Напиши вопрос следующим сообщением.", reply_markup=MAIN_KEYBOARD if is_private(update) else None)
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

    await update.effective_message.reply_text(
        "Выбери действие кнопкой ниже или напиши /help.",
        reply_markup=MAIN_KEYBOARD if is_private(update) else private_link_markup(context),
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
    app.add_handler(MessageHandler(filters.Regex(r"^onboarding:"), onboarding_callback))
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
