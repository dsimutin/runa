from pathlib import Path

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

import bot
import product_runtime
from human_reading import HUMAN_READING_BUTTON, HUMAN_READING_TEXT
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

VERSION_MARKER = "RUNA FINAL 2026-05-07-3"
ALLOWED_OPERATOR_USERNAMES = {"mrgrief", "richstewardess"}
PREMIUM_DIR_CANDIDATES = ["premium", "Premium", "Премиум", "премиум"]
IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp"]


def robust_get_rune_image_path(rune: dict, palette: str) -> str | None:
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
        await update.effective_message.reply_text("Открой личку с ботом. Там появится меню.", reply_markup=bot.private_link_markup(context))
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
        await update.effective_message.reply_text("Не получилось настроить профиль. Попробуй позже.", reply_markup=bot.MAIN_KEYBOARD)
        return
    await update.effective_message.reply_text(f"🜂 {name}, бот обновлён.\n\nВерсия: {VERSION_MARKER}\n\nВыбери действие ниже.", reply_markup=bot.MAIN_KEYBOARD)


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
        await query.edit_message_text("Не получилось сохранить ответ. Нажми /start и попробуй снова.")
        return
    if result.get("completed"):
        await query.edit_message_text(product_runtime.onboarding_result_text(result["palette"]))
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text=(
                "👇 Что можно сделать:\n\n"
                "🌞 Руна дня — фокус на сегодня\n"
                "❓ Вопрос — быстрый ответ одной картой\n"
                "🔮 Расклад — разбор ситуации (3 карты)\n"
                "🕯 Личный расклад — ответ человека\n"
                "⚙️ Настройки — сменить колоду\n\n"
                "Выбери действие ниже"
            ),
            reply_markup=bot.MAIN_KEYBOARD,
        )
        return
    next_step = result["next_step"]
    await query.edit_message_text(product_runtime.build_onboarding_question(next_step, bot.user_name(update)), reply_markup=product_runtime.onboarding_keyboard(next_step))


async def human_reading_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await bot.ensure_profile_ready(update, context):
        return
    context.user_data["state"] = product_runtime.STATE_WAITING_HUMAN
    await bot.send_private_or_group(update, context, HUMAN_READING_TEXT)


async def handle_human_request(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    user = update.effective_user
    if not user:
        return
    palette = bot.get_user_palette(update)
    try:
        init_support_db(bot.DB_PATH)
        request_id = create_request(bot.DB_PATH, user.id, text, palette)
        operator_ids = list_operator_ids(bot.DB_PATH, ALLOWED_OPERATOR_USERNAMES)
    except SupportRequestError:
        bot.logger.exception("Failed to create human reading request")
        await bot.send_private_or_group(update, context, "Не получилось создать заявку. Попробуй чуть позже.")
        return
    admin_note = f"🕯 Новая заявка #{request_id}\n\nКолода: {product_runtime.PALETTE_NAMES.get(palette, palette)}\n\nВопрос:\n{text}\n\nКоманды:\n/claim {request_id} — взять в работу\n/answer {request_id} текст — ответить пользователю"
    notified = False
    for operator_id in operator_ids:
        try:
            await context.bot.send_message(chat_id=operator_id, text=admin_note)
            notified = True
        except TelegramError:
            bot.logger.exception("Failed to notify registered operator")
    for admin_id in bot.ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=admin_note)
            notified = True
        except TelegramError:
            bot.logger.exception("Failed to notify admin id")
    await bot.send_private_or_group(update, context, f"🕯 Вопрос принят.\n\nЗаявка #{request_id}. Человек подключится к раскладу в течение 5–10 минут.\n\nМожно оставаться здесь — ответ придёт прямо в этот чат от бота." + ("" if notified else "\n\nОператору пока не удалось отправить уведомление. Мы сохранили заявку."))


async def final_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.effective_message.text or "").strip()
    state = context.user_data.get("state")

    if text == "🌞 Руна дня":
        await product_runtime.product_runa_command(update, context)
        return
    if text in {"❓ Вопрос", "❓ Задать вопрос"}:
        context.user_data["state"] = bot.STATE_WAITING_ASK
        await update.effective_message.reply_text("❓ Напиши вопрос следующим сообщением.", reply_markup=bot.MAIN_KEYBOARD if bot.is_private(update) else None)
        return
    if text == "🔮 Расклад":
        context.user_data["state"] = bot.STATE_WAITING_RASKLAD
        await update.effective_message.reply_text("🔮 Напиши вопрос для расклада следующим сообщением.", reply_markup=bot.MAIN_KEYBOARD if bot.is_private(update) else None)
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

    await update.effective_message.reply_text("Выбери действие кнопкой ниже или напиши /help.", reply_markup=bot.MAIN_KEYBOARD if bot.is_private(update) else bot.private_link_markup(context))


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
        register_operator(bot.DB_PATH, user.id, username)
    except SupportRequestError:
        await update.effective_message.reply_text("Не получилось зарегистрировать оператора.")
        return
    await update.effective_message.reply_text("Готово. Теперь сюда будут приходить заявки на личный расклад.")


async def claim_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not user.username or user.username.lower() not in ALLOWED_OPERATOR_USERNAMES:
        await update.effective_message.reply_text("Эта команда доступна только операторам.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("Формат: /claim 1047")
        return
    request_id = int(context.args[0])
    try:
        request = claim_request(bot.DB_PATH, request_id, user.id, user.username)
    except SupportRequestError:
        await update.effective_message.reply_text("Не получилось взять заявку.")
        return
    if not request:
        await update.effective_message.reply_text("Заявка не найдена.")
        return
    await update.effective_message.reply_text(f"Заявка #{request_id} взята в работу.")
    try:
        await context.bot.send_message(chat_id=request["user_id"], text=f"🕯 Человек подключился к раскладу.\n\nЗаявка #{request_id} уже в работе. Обычно ответ занимает 5–10 минут.\n\nОтвет придёт сюда же, от бота.")
    except TelegramError:
        bot.logger.exception("Failed to notify user about claim")


async def answer_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not user.username or user.username.lower() not in ALLOWED_OPERATOR_USERNAMES:
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
    try:
        await context.bot.send_message(chat_id=request["user_id"], text=f"🕯 Личный расклад #{request_id}\n\n{answer_text}", reply_markup=bot.MAIN_KEYBOARD)
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
    app.add_handler(CommandHandler("claim", claim_command))
    app.add_handler(CommandHandler("answer", answer_command))
    app.add_handler(CallbackQueryHandler(final_onboarding_callback, pattern=r"^onboarding:"))
    app.add_handler(CallbackQueryHandler(product_runtime.settings_callback, pattern=r"^settings:deck:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, final_text_router))
    app.add_error_handler(bot.error_handler)
    return app


bot.get_rune_image_path = robust_get_rune_image_path
bot.build_application = final_build_application
product_runtime.human_reading_command = human_reading_command
product_runtime.handle_human_request = handle_human_request

if __name__ == "__main__":
    bot.main()
