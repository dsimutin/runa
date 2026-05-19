import re
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

import bot
import product_runtime
from human_reading import (
    HUMAN_READING_BUTTON,
    HUMAN_READING_CANCEL_TEXT,
    HUMAN_READING_PAID_PROMPT,
    HUMAN_READING_TEXT,
    PAYMENT_AMOUNT,
    PAYMENT_CANCEL_CALLBACK,
    PAYMENT_CONFIRM_CALLBACK,
)
from support_requests import (
    SupportRequestError,
    claim_request,
    close_request,
    create_request,
    get_request,
    init_support_db,
    list_operator_ids,
    register_operator,
)

VERSION_MARKER = "RUNA FINAL 2026-05-07-6"
ALLOWED_OPERATOR_USERNAMES = {"mrgrief", "richstewardess"}
PREMIUM_DIR_CANDIDATES = ["premium", "Premium", "Премиум", "премиум"]
IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp"]
REQUEST_ID_RE = re.compile(r"заявка\s*#\s*(\d+)", re.IGNORECASE)


def is_operator_chat(update: Update) -> bool:
    chat = update.effective_chat
    return bool(chat and chat.id in bot.ADMIN_IDS and chat.type != "private")


def is_authorized_operator(update: Update) -> bool:
    user = update.effective_user
    chat = update.effective_chat
    if chat and chat.id in bot.ADMIN_IDS:
        return True
    return bool(user and user.username and user.username.lower() in ALLOWED_OPERATOR_USERNAMES)


def extract_request_id_from_reply(update: Update) -> int | None:
    message = update.effective_message
    if not message or not message.reply_to_message:
        return None
    source_text = message.reply_to_message.text or message.reply_to_message.caption or ""
    match = REQUEST_ID_RE.search(source_text)
    if not match:
        return None
    return int(match.group(1))


def robust_get_rune_image_path(rune: dict, palette: str) -> str | None:
    palette_images = rune.get("palette_image_files")
    if palette_images:
        image_file = palette_images.get(palette) or palette_images.get("light", "")
    else:
        image_file = rune.get("image_file") or ""
    rune_key = (rune.get("key") or "").lower().strip()
    wanted_stem = Path(image_file).stem.lower()
    deck_dirs = PREMIUM_DIR_CANDIDATES if palette == "premium" else [bot.DECK_DIRS.get(palette, "light")]
    folders = []
    for deck_dir in deck_dirs:
        folders.append(Path(bot.BASE_DIR) / deck_dir)
        folders.append(Path(bot.BASE_DIR) / "decks" / deck_dir)
    for folder in folders:
        exact = folder / image_file
        if exact.exists():
            return str(exact)
    for folder in folders:
        if not folder.exists() or not folder.is_dir():
            continue
        files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
        for p in files:
            if p.name.lower() == image_file.lower():
                return str(p)
        if rune_key:
            for p in files:
                if rune_key in p.stem.lower():
                    return str(p)
        clean_stem = wanted_stem.split("-", 1)[-1]
        if clean_stem:
            for p in files:
                if clean_stem in p.stem.lower():
                    return str(p)
    bot.logger.warning("Rune image not found robustly: palette=%s rune=%s image_file=%s folders=%s", palette, rune_key, image_file, folders)
    return None


bot.get_rune_image_path = robust_get_rune_image_path


async def final_start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    if not update.effective_user or not update.effective_message:
        return
    if not bot.is_private(update):
        await update.effective_message.reply_text("Чтобы открыть меню, напиши мне в личку.", reply_markup=bot.private_link_markup(context))
        return
    name = bot.user_name(update)
    try:
        bot.ensure_user(bot.DB_PATH, update.effective_user.id, name)
        profile = bot.get_user_profile(bot.DB_PATH, update.effective_user.id)
        if not profile or not profile.get("palette"):
            bot.start_onboarding(bot.DB_PATH, update.effective_user.id)
            await update.effective_message.reply_text(product_runtime.build_onboarding_question(1, name), reply_markup=product_runtime.onboarding_keyboard(1))
            return
    except bot.DatabaseError:
        bot.logger.exception("Failed to start final onboarding")
        await update.effective_message.reply_text("Что-то пошло не так. Попробуй ещё раз через минуту.", reply_markup=bot.MAIN_KEYBOARD)
        return
    await update.effective_message.reply_text(f"{name}, всё готово. С чего начнём?", reply_markup=bot.MAIN_KEYBOARD)


async def final_onboarding_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user:
        return
    await query.answer()
    try:
        _, step_raw, answer = query.data.split(":", 2)
        int(step_raw)
        result = bot.save_onboarding_answer(bot.DB_PATH, update.effective_user.id, answer, len(bot.ONBOARDING_QUESTIONS))
    except Exception:
        bot.logger.exception("Final onboarding failed")
        await query.edit_message_text("Ответ не сохранился. Нажми /start и попробуем заново.")
        return
    if result.get("completed"):
        await query.edit_message_text(product_runtime.onboarding_result_text(result["palette"]))
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text=(
                "👇 С чего начнём:\n\n"
                "🌞 Руна дня — фокус на сегодня\n"
                "❓ Вопрос (да/нет) — короткий ответ одной картой\n"
                "🔮 Расклад — разбор ситуации на три карты\n"
                "🕯 Личный расклад — живой ответ человека\n"
                "⚙️ Настройки — сменить колоду\n\n"
                "Можно нажать кнопку ниже."
            ),
            reply_markup=bot.MAIN_KEYBOARD,
        )
        return
    next_step = result["next_step"]
    await query.edit_message_text(product_runtime.build_onboarding_question(next_step, bot.user_name(update)), reply_markup=product_runtime.onboarding_keyboard(next_step))


def _payment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Я оплатил", callback_data=PAYMENT_CONFIRM_CALLBACK)],
        [InlineKeyboardButton("✖ Отмена", callback_data=PAYMENT_CANCEL_CALLBACK)],
    ])


async def human_reading_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await bot.ensure_profile_ready(update, context):
        return
    context.user_data.pop("state", None)
    context.user_data["human_reading_payment_pending"] = True
    message = update.effective_message
    if not message:
        return
    await message.reply_text(
        HUMAN_READING_TEXT,
        parse_mode=ParseMode.HTML,
        reply_markup=_payment_keyboard(),
        disable_web_page_preview=True,
    )


async def human_reading_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    if query.data == PAYMENT_CANCEL_CALLBACK:
        context.user_data.pop("human_reading_payment_pending", None)
        context.user_data.pop("state", None)
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except TelegramError:
            pass
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text=HUMAN_READING_CANCEL_TEXT,
            reply_markup=bot.MAIN_KEYBOARD,
        )
        return
    if query.data == PAYMENT_CONFIRM_CALLBACK:
        if not context.user_data.get("human_reading_payment_pending"):
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text="Нажми «🕯 Личный расклад» в меню, чтобы оформить новую заявку.",
                reply_markup=bot.MAIN_KEYBOARD,
            )
            return
        context.user_data["human_reading_payment_claimed"] = True
        context.user_data["state"] = product_runtime.STATE_WAITING_HUMAN
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except TelegramError:
            pass
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text=HUMAN_READING_PAID_PROMPT,
            reply_markup=bot.MAIN_KEYBOARD,
        )


async def handle_human_request(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    user = update.effective_user
    if not user:
        return
    palette = bot.get_user_palette(update)
    try:
        init_support_db(bot.DB_PATH)
        request_id = create_request(bot.DB_PATH, user.id, text, palette)
        registered_operator_ids = list_operator_ids(bot.DB_PATH, ALLOWED_OPERATOR_USERNAMES)
    except SupportRequestError:
        bot.logger.exception("Failed to create human reading request")
        await bot.send_private_or_group(update, context, "Не получилось создать заявку. Попробуй чуть позже.")
        return

    target_ids = set(bot.ADMIN_IDS) or set(registered_operator_ids)
    sender = f"@{user.username}" if user.username else (user.first_name or str(user.id))
    payment_claimed = context.user_data.pop("human_reading_payment_claimed", False)
    context.user_data.pop("human_reading_payment_pending", None)
    payment_line = (
        f"💳 Оплата: пользователь подтвердил перевод {PAYMENT_AMOUNT} ₽. ПРОВЕРЬ ПОСТУПЛЕНИЕ перед ответом."
        if payment_claimed
        else "💳 Оплата: НЕ подтверждена пользователем."
    )
    admin_note = (
        f"🕯 Новая заявка #{request_id}\n\n"
        f"От: {sender}\n"
        f"User ID: {user.id}\n"
        f"Колода: {product_runtime.PALETTE_NAMES.get(palette, palette)}\n"
        f"{payment_line}\n\n"
        f"Вопрос:\n{text}\n\n"
        "Нажми «Ответить» на это сообщение и напиши текст ответа.\n"
        "Бот отправит пользователю именно то, что ты напишешь."
    )
    delivered_to = []
    for chat_id in target_ids:
        try:
            await context.bot.send_message(chat_id=chat_id, text=admin_note)
            delivered_to.append(chat_id)
        except TelegramError:
            bot.logger.exception("Failed to notify personal reading operator chat_id=%s", chat_id)

    if delivered_to:
        await bot.send_private_or_group(update, context, f"🕯 Вопрос получили.\n\nЗаявка #{request_id} — человек подключится в течение 5–10 минут. Можешь не уходить из чата: ответ придёт прямо сюда.")
        return
    await bot.send_private_or_group(update, context, f"🕯 Заявка #{request_id} сохранена.\n\nНо операторский чат пока не получил уведомление. Проверь ADMIN_IDS в Render.")


async def handle_operator_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return
    request_id = extract_request_id_from_reply(update)
    if request_id is None:
        await message.reply_text("Чтобы ответ ушёл пользователю, нажми «Ответить» на сообщение заявки и пришли текст или фото.")
        return
    try:
        request = get_request(bot.DB_PATH, request_id)
    except SupportRequestError:
        bot.logger.exception("Failed to load request from operator reply")
        await message.reply_text("Не получилось найти заявку.")
        return
    if not request:
        await message.reply_text("Заявка не найдена.")
        return
    if request.get("status") == "answered":
        await message.reply_text("Эта заявка уже закрыта.")
        return
    user_id = request["user_id"]
    try:
        if message.photo:
            photo_file_id = message.photo[-1].file_id
            caption = (message.caption or "").strip() or None
            await context.bot.send_photo(
                chat_id=user_id,
                photo=photo_file_id,
                caption=caption,
                reply_markup=bot.MAIN_KEYBOARD,
            )
        elif message.document:
            caption = (message.caption or "").strip() or None
            await context.bot.send_document(
                chat_id=user_id,
                document=message.document.file_id,
                caption=caption,
                reply_markup=bot.MAIN_KEYBOARD,
            )
        elif message.text:
            await context.bot.send_message(
                chat_id=user_id,
                text=message.text.strip(),
                reply_markup=bot.MAIN_KEYBOARD,
            )
        else:
            await message.reply_text("Поддерживаются текст, фото и документ. Пришли реплаем на заявку.")
            return
        close_request(bot.DB_PATH, request_id)
    except (TelegramError, SupportRequestError):
        bot.logger.exception("Failed to send operator reply to user")
        await message.reply_text("Не получилось отправить ответ пользователю.")
        return
    await message.reply_text(f"Готово. Ответ по заявке #{request_id} отправлен пользователю.")


async def operator_media_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_operator_chat(update):
        return
    await handle_operator_reply(update, context)


async def final_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.effective_message.text or "").strip()
    state = context.user_data.get("state")
    if is_operator_chat(update):
        await handle_operator_reply(update, context)
        return
    if text == "🌞 Руна дня":
        await product_runtime.product_runa_command(update, context)
        return
    if text in {"❓ Вопрос", "❓ Задать вопрос", "❓ Вопрос (да/нет)"}:
        context.user_data["state"] = bot.STATE_WAITING_ASK
        await update.effective_message.reply_text("❓ Напиши свой вопрос — отвечу одной картой в формате «да / нет / зависит».", reply_markup=bot.MAIN_KEYBOARD if bot.is_private(update) else None)
        return
    if text == "🔮 Расклад":
        context.user_data["state"] = bot.STATE_WAITING_RASKLAD
        await update.effective_message.reply_text("🔮 Напиши вопрос — раскину три карты на ситуацию.", reply_markup=bot.MAIN_KEYBOARD if bot.is_private(update) else None)
        return
    if text == product_runtime.SETTINGS_BUTTON:
        await product_runtime.settings_command(update, context)
        return
    if text == HUMAN_READING_BUTTON:
        await human_reading_command(update, context)
        return
    if text == "ℹ️ Помощь":
        await product_runtime.bot.help_command(update, context)
        return
    if state == product_runtime.STATE_WAITING_HUMAN:
        context.user_data.pop("state", None)
        await handle_human_request(update, context, text)
        return
    if state == bot.STATE_WAITING_ASK:
        context.user_data.pop("state", None)
        await product_runtime.product_send_one_rune_answer(update, context, text)
        return
    if state == bot.STATE_WAITING_RASKLAD:
        context.user_data.pop("state", None)
        await product_runtime.bot.send_rasklad(update, context, text)
        return
    await update.effective_message.reply_text("Выбери действие на клавиатуре. Или напиши /help, если потерялся.", reply_markup=bot.MAIN_KEYBOARD if bot.is_private(update) else bot.private_link_markup(context))


async def operator_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not user.username:
        await update.effective_message.reply_text("У оператора должен быть username в Telegram.")
        return
    username = user.username.lower()
    if username not in ALLOWED_OPERATOR_USERNAMES:
        await update.effective_message.reply_text("Эта команда доступна только операторам.")
        return
    try:
        init_support_db(bot.DB_PATH)
        register_operator(bot.DB_PATH, user.id, username)
    except SupportRequestError:
        await update.effective_message.reply_text("Не получилось зарегистрировать оператора.")
        return
    await update.effective_message.reply_text(f"Готово. @{username} зарегистрирован как оператор.\n\nТвой numeric ID: {user.id}\nТеперь сюда будут приходить заявки на личный расклад.")


async def whoami_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return
    await update.effective_message.reply_text(f"User ID: {user.id}\nChat ID: {chat.id}\nUsername: @{user.username}" if user.username else f"User ID: {user.id}\nChat ID: {chat.id}")


async def claim_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text("Теперь не нужно брать заявку командой. Ответьте реплаем на сообщение заявки.")


async def answer_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized_operator(update):
        await update.effective_message.reply_text("Эта команда доступна только операторам.")
        return
    if not context.args or not context.args[0].isdigit() or len(context.args) < 2:
        await update.effective_message.reply_text("Формат: /answer 1047 текст ответа")
        return
    request_id = int(context.args[0])
    answer_text = " ".join(context.args[1:]).strip()
    try:
        request = get_request(bot.DB_PATH, request_id)
    except SupportRequestError:
        await update.effective_message.reply_text("Не получилось найти заявку.")
        return
    if not request:
        await update.effective_message.reply_text("Заявка не найдена.")
        return
    if request.get("status") == "answered":
        await update.effective_message.reply_text("Эта заявка уже закрыта.")
        return
    try:
        await context.bot.send_message(chat_id=request["user_id"], text=answer_text, reply_markup=bot.MAIN_KEYBOARD)
        close_request(bot.DB_PATH, request_id)
    except (TelegramError, SupportRequestError):
        await update.effective_message.reply_text("Не получилось отправить ответ пользователю.")
        return
    await update.effective_message.reply_text(f"Ответ по заявке #{request_id} отправлен.")


def final_build_application():
    if not bot.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set. Add it in environment variables.")
    bot.init_db(bot.DB_PATH)
    init_support_db(bot.DB_PATH)
    app = bot.Application.builder().token(bot.BOT_TOKEN).post_init(bot.post_init).build()
    app.add_handler(CommandHandler("start", final_start_command))
    app.add_handler(CommandHandler("help", product_runtime.bot.help_command))
    app.add_handler(CommandHandler("profile", product_runtime.bot.profile_command))
    app.add_handler(CommandHandler("check_decks", product_runtime.bot.check_decks_command))
    app.add_handler(CommandHandler("runa", product_runtime.product_runa_command))
    app.add_handler(CommandHandler("ask", product_runtime.bot.ask_command))
    app.add_handler(CommandHandler("rasklad", product_runtime.bot.rasklad_command))
    app.add_handler(CommandHandler("operator", operator_command))
    app.add_handler(CommandHandler("whoami", whoami_command))
    app.add_handler(CommandHandler("claim", claim_command))
    app.add_handler(CommandHandler("answer", answer_command))
    app.add_handler(CallbackQueryHandler(final_onboarding_callback, pattern=r"^onboarding:"))
    app.add_handler(CallbackQueryHandler(product_runtime.settings_callback, pattern=r"^settings:deck:"))
    app.add_handler(CallbackQueryHandler(human_reading_payment_callback, pattern=r"^human_reading:"))
    app.add_handler(MessageHandler((filters.PHOTO | filters.Document.ALL) & ~filters.COMMAND, operator_media_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, final_text_router))
    app.add_error_handler(bot.error_handler)
    return app


bot.get_rune_image_path = robust_get_rune_image_path
bot.build_application = final_build_application
product_runtime.human_reading_command = human_reading_command
product_runtime.handle_human_request = handle_human_request

if __name__ == "__main__":
    bot.main()
