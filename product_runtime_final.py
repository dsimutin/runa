import os
from pathlib import Path

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import CommandHandler, ContextTypes

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

ALLOWED_OPERATOR_USERNAMES = {"mrgrief", "richstewardess"}
PREMIUM_DIR_CANDIDATES = ["premium", "Premium", "Премиум", "премиум"]
IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp"]


def robust_get_rune_image_path(rune: dict, palette: str) -> str | None:
    image_file = rune.get("image_file") or ""
    rune_key = (rune.get("key") or "").lower().strip()
    wanted_stem = Path(image_file).stem.lower()
    wanted_ext = Path(image_file).suffix.lower()

    if palette == "premium":
        deck_dirs = PREMIUM_DIR_CANDIDATES
    else:
        deck_dirs = [bot.DECK_DIRS.get(palette, "light")]

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

        if wanted_stem:
            clean_stem = wanted_stem.split("-", 1)[-1]
            for p in files:
                if clean_stem and clean_stem in p.stem.lower():
                    return str(p)

        if wanted_ext:
            for p in files:
                if p.stem.lower() == wanted_stem and p.suffix.lower() != wanted_ext:
                    return str(p)

    bot.logger.warning("Rune image not found robustly: palette=%s rune=%s image_file=%s folders=%s", palette, rune_key, image_file, folders)
    return None


bot.get_rune_image_path = robust_get_rune_image_path


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

    admin_note = (
        f"🕯 Новая заявка #{request_id}\n\n"
        f"Колода: {product_runtime.PALETTE_NAMES.get(palette, palette)}\n\n"
        f"Вопрос:\n{text}\n\n"
        f"Команды:\n/claim {request_id} — взять в работу\n/answer {request_id} текст — ответить пользователю"
    )

    notified = False
    for operator_id in operator_ids:
        try:
            await context.bot.send_message(chat_id=operator_id, text=admin_note)
            notified = True
        except TelegramError:
            bot.logger.exception("Failed to notify registered operator")

    # Fallback: if operators have not registered with /operator, try configured admin IDs.
    for admin_id in bot.ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=admin_note)
            notified = True
        except TelegramError:
            bot.logger.exception("Failed to notify admin id")

    await bot.send_private_or_group(
        update,
        context,
        f"🕯 Вопрос принят.\n\n"
        f"Заявка #{request_id}. Человек подключится к раскладу в течение 5–10 минут.\n\n"
        "Можно оставаться здесь — ответ придёт прямо в этот чат от бота."
        + ("" if notified else "\n\nОператору пока не удалось отправить уведомление. Мы сохранили заявку."),
    )


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
        bot.logger.exception("Failed to register operator")
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
        bot.logger.exception("Failed to claim request")
        await update.effective_message.reply_text("Не получилось взять заявку.")
        return
    if not request:
        await update.effective_message.reply_text("Заявка не найдена.")
        return
    await update.effective_message.reply_text(f"Заявка #{request_id} взята в работу.")
    try:
        await context.bot.send_message(
            chat_id=request["user_id"],
            text=(
                f"🕯 Человек подключился к раскладу.\n\n"
                f"Заявка #{request_id} уже в работе. Обычно ответ занимает 5–10 минут.\n\n"
                "Ответ придёт сюда же, от бота."
            ),
        )
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
        bot.logger.exception("Failed to load request")
        await update.effective_message.reply_text("Не получилось найти заявку.")
        return
    if not request:
        await update.effective_message.reply_text("Заявка не найдена.")
        return
    try:
        await context.bot.send_message(
            chat_id=request["user_id"],
            text=f"🕯 Личный расклад #{request_id}\n\n{answer_text}",
            reply_markup=bot.MAIN_KEYBOARD,
        )
        close_request(bot.DB_PATH, request_id)
    except (TelegramError, SupportRequestError):
        bot.logger.exception("Failed to send answer")
        await update.effective_message.reply_text("Не получилось отправить ответ пользователю.")
        return
    await update.effective_message.reply_text(f"Ответ по заявке #{request_id} отправлен.")


async def final_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.effective_message.text or "").strip()
    if text == HUMAN_READING_BUTTON:
        await human_reading_command(update, context)
        return
    state = context.user_data.get("state")
    if state == product_runtime.STATE_WAITING_HUMAN:
        context.user_data.pop("state", None)
        await handle_human_request(update, context, text)
        return
    await product_runtime.product_text_router(update, context)


old_build_application = bot.build_application


def final_build_application():
    app = old_build_application()
    app.add_handler(CommandHandler("operator", operator_command))
    app.add_handler(CommandHandler("claim", claim_command))
    app.add_handler(CommandHandler("answer", answer_command))
    return app


bot.text_router = final_text_router
bot.build_application = final_build_application
product_runtime.human_reading_command = human_reading_command
product_runtime.handle_human_request = handle_human_request
product_runtime.product_text_router = final_text_router

if __name__ == "__main__":
    bot.main()
