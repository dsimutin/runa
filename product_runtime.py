import hashlib
import random
from datetime import date

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import CallbackQueryHandler, ContextTypes

import bot
from database import set_user_palette
from human_reading import HUMAN_READING_BUTTON, HUMAN_READING_TEXT
from rune_states import ALT_RATE, alt_meaning
from runes_data import RUNES, get_rune_by_name

STATE_WAITING_HUMAN = "waiting_human"
SETTINGS_BUTTON = "⚙️ Настройки"
PALETTE_NAMES = {"light": "Светлая", "dark": "Тёмная", "premium": "Премиум"}

bot.DECK_DIRS = {"light": "light", "dark": "dark", "premium": "Премиум"}

bot.MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [["🌞 Руна дня", "❓ Вопрос"], ["🔮 Расклад", HUMAN_READING_BUTTON], [SETTINGS_BUTTON, "ℹ️ Помощь"]],
    resize_keyboard=True,
    is_persistent=True,
)

bot.ONBOARDING_QUESTIONS = [
    {
        "text": "Ты входишь в незнакомое пространство. Что считываешь первым?",
        "a": "Атмосферу, свет, воздух, внутреннее ощущение",
        "b": "Границы, правила, риски и кто управляет ситуацией",
        "c": "Детали, символы, скрытый смысл и общее напряжение",
    },
    {
        "text": "Когда внутри нет ясности, что тебе ближе?",
        "a": "Пауза и мягкое прояснение",
        "b": "Прямой ответ и действие",
        "c": "Глубокий разбор, где важны нюансы и подтекст",
    },
    {
        "text": "Какой образ сильнее откликается сейчас?",
        "a": "Тёплый луч на закрытой двери",
        "b": "Ключ в тёмной комнате",
        "c": "Зеркало из тёмного металла с тонким золотым краем",
    },
    {
        "text": "Как ты обычно принимаешь важное решение?",
        "a": "Слушаю состояние и выбираю то, где становится спокойнее",
        "b": "Сравниваю факты, риски и последствия",
        "c": "Смотрю на общий рисунок: что повторяется и куда ведёт линия событий",
    },
    {
        "text": "Какого ответа ты ждёшь от рун?",
        "a": "Бережного ориентира",
        "b": "Честного предупреждения",
        "c": "Глубокой интерпретации без лишней мистики",
    },
]


def stable_alt(user_id: int, day: str, rune_key: str) -> bool:
    raw = f"{user_id}:{day}:{rune_key}".encode("utf-8")
    value = int(hashlib.sha256(raw).hexdigest()[:8], 16) / 0xFFFFFFFF
    return value < ALT_RATE


def random_alt() -> bool:
    return random.random() < ALT_RATE


def rune_title(rune: dict, alt: bool) -> str:
    return f"{rune['name']} — обратное положение" if alt else rune["name"]


def get_user_palette(update: Update) -> str:
    user = update.effective_user
    if not user:
        return "light"
    try:
        profile = bot.get_user_profile(bot.DB_PATH, user.id)
        if profile and profile.get("palette") in {"light", "dark", "premium"}:
            return profile["palette"]
    except bot.DatabaseError:
        bot.logger.exception("Failed to get user palette")
    return "light"


bot.get_user_palette = get_user_palette


def onboarding_keyboard(step: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("A", callback_data=f"onboarding:{step}:light")],
            [InlineKeyboardButton("B", callback_data=f"onboarding:{step}:dark")],
            [InlineKeyboardButton("C", callback_data=f"onboarding:{step}:premium")],
        ]
    )


bot.onboarding_keyboard = onboarding_keyboard


def build_onboarding_question(step: int, name: str) -> str:
    q = bot.ONBOARDING_QUESTIONS[step - 1]
    return (
        f"🜂 {name}, настроим твою колоду\n\n"
        f"Вопрос {step}/5\n"
        f"{q['text']}\n\n"
        f"A — {q['a']}\n"
        f"B — {q['b']}\n"
        f"C — {q['c']}"
    )


bot.build_onboarding_question = build_onboarding_question


def onboarding_result_text(palette: str) -> str:
    if palette == "premium":
        return (
            "🜂 Колода настроена\n\n"
            "Тебе подошла колода: Премиум.\n\n"
            "Она будет читать ситуацию глубже: через подтекст, повторяющиеся сигналы и скрытую структуру вопроса.\n\n"
            "Колоду можно поменять вручную в ⚙️ Настройках."
        )
    profile = bot.PSYCHOTYPES[palette]
    deck = PALETTE_NAMES[palette]
    return (
        "🜂 Колода настроена\n\n"
        f"Тебе подошла колода: {deck}.\n"
        f"Стиль чтения: {profile['reading_style']}.\n\n"
        "Колоду можно поменять вручную в ⚙️ Настройках."
    )


bot.onboarding_result_text = onboarding_result_text


def product_daily_text(name: str, main: dict, main_text: dict, aux: dict, aux_text: dict, palette: str, main_alt: bool, aux_alt: bool) -> str:
    if palette == "premium":
        opening = f"🜁 {name}, сегодня важен не сам знак, а то, какой слой он открывает."
        middle = "Глубинный смысл"
        action = "Не принимай решение по первому импульсу. Посмотри, какой сценарий повторяется, и убери из него один лишний элемент."
        signal_label = "Второй слой"
    elif palette == "dark":
        opening = f"🌑 {name}, ситуация уже просит ясности."
        middle = "Что важно понять"
        action = "Назови главное напряжение прямо. Один честный шаг сейчас сильнее долгого ожидания."
        signal_label = "Дополнительный сигнал"
    else:
        opening = f"🌞 {name}, сегодня пространство говорит тише обычного."
        middle = "Что это меняет"
        action = "Убери один лишний фокус. Освободи место для главного."
        signal_label = "Дополнительный сигнал"

    main_desc = alt_meaning(main) if main_alt else main_text["short_desc"]
    aux_desc = alt_meaning(aux) if aux_alt else aux_text["short_desc"]
    return (
        f"{opening}\n\n"
        f"{rune_title(main, main_alt)}\n\n"
        f"{main_desc}\n\n"
        f"{middle}\n"
        "Смотри не только на событие, а на рисунок, который оно повторяет.\n\n"
        f"{signal_label} — {rune_title(aux, aux_alt)}\n\n"
        f"{aux_desc}\n\n"
        "Что сделать\n"
        f"{action}"
    )


def product_question_text(name: str, question: str, rune: dict, answer: str, palette: str, alt: bool) -> str:
    if palette == "premium":
        opening = f"🜁 {name}, здесь важен скрытый слой вопроса."
        final = "Не ищи быстрый ответ. Сначала определи, что в этой ситуации повторяется и почему ты снова смотришь именно туда."
        marker = "Что открывает руна"
    elif palette == "dark":
        opening = f"🌑 {name}, ответ здесь не мягкий — он точный."
        final = "Не обходи главный факт. Проверь, где ты уже знаешь решение, но тянешь с действием."
        marker = "Что руна показывает"
    else:
        opening = f"🌞 {name}, руна отвечает не прямо, а через внутренний сигнал."
        final = "Не торопись с выводом. Сначала отдели реальное ощущение от шума вокруг ситуации."
        marker = "Что руна показывает"
    body = alt_meaning(rune) if alt else answer
    return (
        f"{opening}\n\n"
        f"Вопрос\n{question}\n\n"
        f"Карта\n{rune_title(rune, alt)}\n\n"
        f"{marker}\n{body}\n\n"
        f"Главное сейчас\n{final}"
    )


async def product_start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    if not update.effective_user or not update.effective_message:
        return
    if not bot.is_private(update):
        await update.effective_message.reply_text("Открой личку с ботом. Там появится меню.", reply_markup=bot.private_link_markup(context))
        return
    name = bot.user_name(update)
    try:
        bot.ensure_user(bot.DB_PATH, update.effective_user.id, name)
        profile = bot.get_user_profile(bot.DB_PATH, update.effective_user.id)
        if not profile or not profile.get("palette"):
            bot.start_onboarding(bot.DB_PATH, update.effective_user.id)
            await update.effective_message.reply_text(bot.build_onboarding_question(1, name), reply_markup=bot.onboarding_keyboard(1))
            return
    except bot.DatabaseError:
        bot.logger.exception("Failed to start onboarding")
        await update.effective_message.reply_text("Не получилось настроить профиль. Попробуй позже.", reply_markup=bot.MAIN_KEYBOARD)
        return
    await update.effective_message.reply_text(f"🜂 {name}, меню снова на месте.\n\nВыбери действие ниже.", reply_markup=bot.MAIN_KEYBOARD)


async def product_runa_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    if not update.effective_user:
        return
    if not await bot.ensure_profile_ready(update, context):
        return
    today = date.today().isoformat()
    try:
        main_name, aux_name = bot.get_or_create_daily_runes(bot.DB_PATH, update.effective_user.id, today, RUNES)
    except bot.DatabaseError:
        bot.logger.exception("Failed to get daily runes")
        await bot.send_private_or_group(update, context, "Не получилось достать руну дня. Попробуй позже.")
        return
    palette = bot.get_user_palette(update)
    main = get_rune_by_name(main_name)
    aux = get_rune_by_name(aux_name)
    image_path = bot.get_rune_image_path(main, palette)
    if not image_path:
        await bot.send_missing_image_error(update, context, main, palette)
        return
    text = product_daily_text(bot.user_name(update), main, bot.rune_text(main, palette if palette != "premium" else "dark"), aux, bot.rune_text(aux, palette if palette != "premium" else "dark"), palette, stable_alt(update.effective_user.id, today, main["key"]), stable_alt(update.effective_user.id, today, aux["key"]))
    await bot.send_private_or_group(update, context, text, image_path=image_path)


async def product_send_one_rune_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str) -> None:
    if not await bot.ensure_profile_ready(update, context):
        return
    palette = bot.get_user_palette(update)
    text_palette = palette if palette != "premium" else "dark"
    rune = random.choice(RUNES)
    image_path = bot.get_rune_image_path(rune, palette)
    if not image_path:
        await bot.send_missing_image_error(update, context, rune, palette)
        return
    text_data = bot.rune_text(rune, text_palette)
    answer = random.choice([text_data["answer_yes"], text_data["answer_no"]])
    text = product_question_text(bot.user_name(update), question, rune, answer, palette, random_alt())
    await bot.send_private_or_group(update, context, text, image_path=image_path)


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await bot.ensure_profile_ready(update, context):
        return
    palette = bot.get_user_palette(update)
    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🌞 Светлая", callback_data="settings:deck:light")],
            [InlineKeyboardButton("🌑 Тёмная", callback_data="settings:deck:dark")],
            [InlineKeyboardButton("🜁 Премиум", callback_data="settings:deck:premium")],
        ]
    )
    await bot.send_private_or_group(update, context, f"⚙️ Настройки\n\nТекущая колода: {PALETTE_NAMES.get(palette, 'Светлая')}\n\nМожно сменить её вручную:", image_path=None)
    await update.effective_message.reply_text("Выбери колоду:", reply_markup=markup)


async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user:
        return
    await query.answer()
    parts = query.data.split(":")
    if len(parts) != 3 or parts[0] != "settings" or parts[1] != "deck":
        return
    palette = parts[2]
    try:
        set_user_palette(bot.DB_PATH, update.effective_user.id, palette)
    except bot.DatabaseError:
        await query.edit_message_text("Не получилось сменить колоду. Попробуй позже.")
        return
    await query.edit_message_text(f"Готово. Теперь используется колода: {PALETTE_NAMES.get(palette, palette)}.")
    await context.bot.send_message(chat_id=update.effective_user.id, text="Меню обновлено.", reply_markup=bot.MAIN_KEYBOARD)


async def human_reading_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await bot.ensure_profile_ready(update, context):
        return
    context.user_data["state"] = STATE_WAITING_HUMAN
    await bot.send_private_or_group(update, context, HUMAN_READING_TEXT)


async def handle_human_request(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    user = update.effective_user
    if not user:
        return
    sender = f"@{user.username}" if user.username else user.first_name or str(user.id)
    admin_note = f"🕯 Новый личный расклад\n\nОт: {sender}\nID: {user.id}\n\nВопрос:\n{text}"
    for admin_id in bot.ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=admin_note)
        except TelegramError:
            bot.logger.exception("Failed to notify admin about human reading")
    await bot.send_private_or_group(update, context, "Принял вопрос. Личный расклад стоит 100 ₽. Ответ подготовит человек, поэтому это займёт немного больше времени.")


old_text_router = bot.text_router
old_build_template_rasklad = bot.build_template_rasklad
old_build_application = bot.build_application


async def product_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.effective_message.text or "").strip()
    if text == HUMAN_READING_BUTTON:
        await human_reading_command(update, context)
        return
    if text == SETTINGS_BUTTON:
        await settings_command(update, context)
        return
    state = context.user_data.get("state")
    if state == STATE_WAITING_HUMAN:
        context.user_data.pop("state", None)
        await handle_human_request(update, context, text)
        return
    await old_text_router(update, context)


def product_build_template_rasklad(name: str, question: str, runes: list, palette: str) -> str:
    text_palette = palette if palette != "premium" else "dark"
    text = old_build_template_rasklad(name, question, runes, text_palette)
    hidden = []
    for rune in runes:
        if random_alt():
            hidden.append(f"— {rune['name']}: {alt_meaning(rune)}")
    if hidden:
        title = "Скрытый слой" if palette != "premium" else "Глубинный слой"
        text += f"\n\n{title}\n" + "\n".join(hidden)
    return text


def patched_short_help() -> str:
    return (
        "ℹ️ Помощь\n\n"
        "🌞 /runa — руна дня\n"
        "❓ /ask <вопрос> — ответ одной картой\n"
        "🔮 /rasklad <вопрос> — расклад на 3 карты\n"
        f"{HUMAN_READING_BUTTON} — живой разбор за 100 ₽\n"
        f"{SETTINGS_BUTTON} — сменить колоду\n"
        "🜂 /profile — твоя колода"
    )


def patched_build_application():
    app = old_build_application()
    app.add_handler(CallbackQueryHandler(settings_callback, pattern=r"^settings:deck:"))
    return app


bot.start_command = product_start_command
bot.runa_command = product_runa_command
bot.send_one_rune_answer = product_send_one_rune_answer
bot.text_router = product_text_router
bot.build_template_rasklad = product_build_template_rasklad
bot.short_help = patched_short_help
bot.build_application = patched_build_application

if __name__ == "__main__":
    bot.main()
