import re
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, ReplyKeyboardRemove, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, PreCheckoutQueryHandler, filters

import bot
import product_runtime
from daily_broadcast import (
    BROADCAST_TIME,
    send_daily_rune,
    send_weekly_question,
    send_premium_expiry_warnings,
    send_monthly_rune,
    subscribe_command,
    unsubscribe_command,
)
from history_command import history_command
from pair_rasklad import pair_rasklad_command
from year_rasklad import send_year_rasklad
from human_reading import (
    HUMAN_READING_BUTTON,
    HUMAN_READING_CANCEL_TEXT,
    HUMAN_READING_PAID_PROMPT,
    HUMAN_READING_TEXT,
    PAYMENT_AMOUNT,
    PAYMENT_CANCEL_CALLBACK,
    PAYMENT_CONFIRM_CALLBACK,
)
from premium_subscription import (
    get_premium_info_text,
    get_premium_keyboard,
    is_premium_active,
    is_trial_active,
    activate_premium,
    activate_trial,
    get_free_readings_left,
    use_free_reading,
    PREMIUM_PRICE_STARS,
    PREMIUM_PRICE_RUB,
    TRIAL_DAYS,
    PAYMENT_PROVIDER_TOKEN,
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

HIDE_KEYBOARD_BUTTON = "🙈 Скрыть меню"


def build_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    """Возвращает клавиатуру с учётом premium статуса пользователя."""
    from premium_subscription import is_premium_active, is_trial_active
    base = [
        ["🌞 Руна дня", "❓ Вопрос (да/нет)"],
        ["🔮 Расклад", "🕯 Личный расклад"],
    ]
    try:
        if is_premium_active(user_id):
            if is_trial_active(user_id):
                base.append(["🗓 Расклад на год", "💠 Премиум"])
            else:
                base.append(["🗓 Расклад на год", "✌️ Расклад на пару"])
                base.append(["💠 Премиум", "⚙️ Настройки"])
        else:
            base.append(["💠 Премиум", "⚙️ Настройки"])
    except Exception:
        base.append(["💠 Премиум", "⚙️ Настройки"])
    base.append(["ℹ️ Помощь", HIDE_KEYBOARD_BUTTON])
    return ReplyKeyboardMarkup(base, resize_keyboard=True)
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
        bot.ensure_user(update.effective_user.id, name)
        profile = bot.get_user_profile(update.effective_user.id)
        if not profile or not profile.get("palette"):
            bot.start_onboarding(update.effective_user.id)
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
        result = bot.save_onboarding_answer(update.effective_user.id, answer, len(bot.ONBOARDING_QUESTIONS))
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
                "🌞 <b>Руна дня</b> — фокус на сегодня\n"
                "❓ <b>Вопрос (да/нет)</b> — короткий ответ одной картой\n"
                "🔮 <b>Расклад</b> — разбор ситуации на три карты\n"
                "🕯 <b>Личный расклад</b> — живой ответ человека\n"
                "⚙️ <b>Настройки</b> — сменить колоду\n\n"
                "Можно нажать кнопку ниже."
            ),
            reply_markup=bot.MAIN_KEYBOARD,
            parse_mode="HTML",
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
    message = update.effective_message
    if not message or not update.effective_user:
        return

    # Trial users cannot use personal readings
    if is_trial_active(update.effective_user.id):
        await message.reply_text(
            "🕯 <b>Личный расклад</b>\n\n"
            "В пробном периоде личные расклады недоступны.\n"
            "Оформи полный премиум — нажми 💠 Премиум в меню.",
            parse_mode=ParseMode.HTML,
            reply_markup=bot.MAIN_KEYBOARD,
        )
        return

    # Paid premium users with free readings go straight to question input
    if is_premium_active(update.effective_user.id):
        free_left = get_free_readings_left(update.effective_user.id)
        if free_left > 0:
            context.user_data["state"] = product_runtime.STATE_WAITING_HUMAN
            context.user_data["human_reading_is_free"] = True
            await message.reply_text(
                f"🕯 <b>Личный расклад</b>\n\n"
                f"У тебя {free_left} бесплатных {'расклад' if free_left == 1 else 'расклада'} по премиуму.\n\n"
                "Напиши вопрос одним сообщением — он уйдёт человеку для разбора.",
                parse_mode=ParseMode.HTML,
                reply_markup=bot.MAIN_KEYBOARD,
            )
            return

    context.user_data["human_reading_payment_pending"] = True
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
        init_support_db()
        request_id = create_request(user.id, text, palette)
        registered_operator_ids = list_operator_ids(ALLOWED_OPERATOR_USERNAMES)
    except SupportRequestError:
        bot.logger.exception("Failed to create human reading request")
        await bot.send_private_or_group(update, context, "Не получилось создать заявку. Попробуй чуть позже.")
        return

    target_ids = set(bot.ADMIN_IDS) or set(registered_operator_ids)
    sender = f"@{user.username}" if user.username else (user.first_name or str(user.id))
    payment_claimed = context.user_data.pop("human_reading_payment_claimed", False)
    is_free = context.user_data.pop("human_reading_is_free", False)
    context.user_data.pop("human_reading_payment_pending", None)
    if is_free:
        use_free_reading(user.id)
        free_left = get_free_readings_left(user.id)
        payment_line = f"💠 Премиум — бесплатный расклад (осталось после этого: {free_left})"
    elif payment_claimed:
        payment_line = f"💳 Оплата: пользователь подтвердил перевод {PAYMENT_AMOUNT} ₽. ПРОВЕРЬ ПОСТУПЛЕНИЕ перед ответом."
    else:
        payment_line = "💳 Оплата: НЕ подтверждена пользователем."
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
    operator_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Взять заявку", callback_data=f"op:claim:{request_id}")],
        [InlineKeyboardButton("❌ Отклонить", callback_data=f"op:decline:{request_id}")],
    ])
    delivered_to = []
    for chat_id in target_ids:
        try:
            await context.bot.send_message(chat_id=chat_id, text=admin_note, reply_markup=operator_kb)
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
        request = get_request(request_id)
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
        close_request(request_id)
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
    user_id = update.effective_user.id if update.effective_user else 0
    if is_operator_chat(update):
        await handle_operator_reply(update, context)
        return
    if text == HIDE_KEYBOARD_BUTTON:
        await update.effective_message.reply_text(
            "Меню скрыто. Напиши любое сообщение или /menu чтобы вернуть его.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    if text == "/menu" or text == "📲 Показать меню":
        await update.effective_message.reply_text(
            "Меню открыто.", reply_markup=build_main_keyboard(user_id)
        )
        return
    if text == "🌞 Руна дня":
        await product_runtime.product_runa_command(update, context)
        return
    if text in {"❓ Вопрос", "❓ Задать вопрос", "❓ Вопрос (да/нет)"}:
        context.user_data["state"] = bot.STATE_WAITING_ASK
        await update.effective_message.reply_text("❓ Напиши свой вопрос — отвечу одной картой.", reply_markup=bot.MAIN_KEYBOARD if bot.is_private(update) else None)
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
    if text == "💠 Премиум":
        await premium_command(update, context)
        return
    if text == "🗓 Расклад на год":
        if not is_premium_active(user_id):
            await update.effective_message.reply_text(
                "🗓 Расклад на год доступен только в премиуме. Нажми 💠 Премиум.",
                reply_markup=build_main_keyboard(user_id),
            )
            return
        await send_year_rasklad(update, context)
        return
    if text == "✌️ Расклад на пару":
        if is_trial_active(user_id):
            await update.effective_message.reply_text(
                "✌️ Расклад на пару доступен только в платном премиуме.",
                reply_markup=build_main_keyboard(user_id),
            )
            return
        context.user_data["state"] = "waiting_pair_name"
        await update.effective_message.reply_text(
            "✌️ Напиши имя человека:", reply_markup=build_main_keyboard(user_id)
        )
        return
    if text == "ℹ️ Помощь":
        await product_runtime.bot.help_command(update, context)
        return
    if state == product_runtime.STATE_WAITING_HUMAN:
        context.user_data.pop("state", None)
        await handle_human_request(update, context, text)
        return
    if state == "waiting_pair_name":
        context.user_data.pop("state", None)
        from pair_rasklad import pair_name_received
        await pair_name_received(update, context, text)
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
        init_support_db()
        register_operator(user.id, username)
    except SupportRequestError:
        await update.effective_message.reply_text("Не получилось зарегистрировать оператора.")
        return
    await update.effective_message.reply_text(f"Готово. @{username} зарегистрирован как оператор.\n\nТвой numeric ID: {user.id}\nТеперь сюда будут приходить заявки на личный расклад.")


async def activatepremium_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Operator command: /activatepremium <user_id> — manually activate premium."""
    if not is_authorized_operator(update):
        await update.effective_message.reply_text("Эта команда доступна только операторам.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("Формат: /activatepremium 123456789")
        return
    target_id = int(context.args[0])
    try:
        activate_premium(target_id)
    except Exception:
        bot.logger.exception("Failed to activate premium for user_id=%s", target_id)
        await update.effective_message.reply_text("Не удалось активировать. Проверь user_id.")
        return
    await update.effective_message.reply_text(f"✅ Премиум активирован для user_id={target_id} на 31 день.")
    try:
        from database import get_premium_status
        status = get_premium_status(target_id)
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                "💠 <b>Премиум активирован!</b>\n\n"
                f"Подписка действует до {status['expires_at']}.\n"
                "Доступна премиум-колода и 3 бесплатных личных расклада в месяц.\n\n"
                "Напиши /premium чтобы проверить статус."
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=bot.MAIN_KEYBOARD,
        )
    except Exception:
        pass


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
        request = get_request(request_id)
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
        close_request(request_id)
    except (TelegramError, SupportRequestError):
        await update.effective_message.reply_text("Не получилось отправить ответ пользователю.")
        return
    await update.effective_message.reply_text(f"Ответ по заявке #{request_id} отправлен.")


def _premium_features_keyboard(on_trial: bool) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("🗓 Расклад на год", callback_data="premium:year")],
    ]
    if not on_trial:
        buttons.append([InlineKeyboardButton("✌️ Расклад на пару", callback_data="premium:pair")])
        buttons.append([InlineKeyboardButton("📅 Настройка дня недели", callback_data="premium:weekday_menu")])
    else:
        buttons.append([InlineKeyboardButton("💳 Оформить полный премиум", callback_data="premium:buy:stars")])
        buttons.append([InlineKeyboardButton("💳 Оплатить картой", callback_data="premium:buy:card")])
    buttons.append([InlineKeyboardButton("✖ Закрыть", callback_data="premium:close")])
    return InlineKeyboardMarkup(buttons)


async def premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await bot.ensure_profile_ready(update, context):
        return
    user = update.effective_user
    if not user:
        return
    message = update.effective_message
    if not message:
        return
    name = bot.user_name(update)
    if is_premium_active(user.id):
        from database import get_premium_status
        status = get_premium_status(user.id)
        expires_str = status.get("expires_at") or status.get("trial_expires_at", "")
        on_trial = is_trial_active(user.id)
        try:
            from datetime import date as _date
            exp_date = _date.fromisoformat(expires_str)
            exp_formatted = exp_date.strftime("%d.%m.%Y")
        except (ValueError, TypeError):
            exp_formatted = expires_str or "неизвестно"
        free_left = get_free_readings_left(user.id)
        label = "Пробный период активен до" if on_trial else "Премиум активен до"
        await message.reply_text(
            f"💠 <b>{label} {exp_formatted}</b>\n\n"
            + (f"Осталось бесплатных личных раскладов: <b>{free_left}</b>\n\n" if not on_trial else "")
            + "Выбери функцию:",
            parse_mode=ParseMode.HTML,
            reply_markup=_premium_features_keyboard(on_trial),
        )
        return
    await message.reply_text(
        get_premium_info_text(name),
        parse_mode=ParseMode.HTML,
        reply_markup=get_premium_keyboard(user.id),
    )


async def premium_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user:
        return
    await query.answer()
    user = update.effective_user
    data = query.data or ""

    if data == "premium:close":
        try:
            await query.delete_message()
        except TelegramError:
            pass
        return

    if data == "premium:trial":
        from premium_subscription import is_trial_used
        if is_trial_used(user.id):
            await query.answer("Пробный период уже был использован.", show_alert=True)
            return
        try:
            expires_at = activate_trial(user.id)
        except Exception:
            bot.logger.exception("Failed to activate trial for user_id=%s", user.id)
            await context.bot.send_message(
                chat_id=user.id,
                text="Не удалось активировать пробный период. Попробуй позже.",
                reply_markup=bot.MAIN_KEYBOARD,
            )
            return
        try:
            await query.delete_message()
        except TelegramError:
            pass
        await context.bot.send_message(
            chat_id=user.id,
            text=(
                f"🎁 <b>Пробный период активирован на {TRIAL_DAYS} дней!</b>\n\n"
                f"Подписка действует до {expires_at}.\n\n"
                "✅ Доступно в пробном периоде:\n"
                "• Премиум-колода\n"
                "• Руна дня\n"
                "• Расклад на год\n\n"
                "❌ Только в платном премиуме:\n"
                "• Расклад на пару\n"
                "• 3 личных расклада в месяц\n"
                "• Настройка дня еженедельной руны"
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=build_main_keyboard(user.id),
        )
        return

    if data == "premium:buy:stars":
        try:
            await context.bot.send_invoice(
                chat_id=user.id,
                title="Премиум-подписка на месяц",
                description="Премиум-колода и 3 бесплатных личных расклада в месяц",
                payload="premium_stars_1month",
                currency="XTR",
                prices=[LabeledPrice("Премиум 1 месяц", PREMIUM_PRICE_STARS)],
            )
        except TelegramError:
            bot.logger.exception("Failed to send Stars invoice")
            await context.bot.send_message(
                chat_id=user.id,
                text="Не удалось создать счёт. Попробуй чуть позже.",
                reply_markup=bot.MAIN_KEYBOARD,
            )
        return

    if data == "premium:buy:card":
        if PAYMENT_PROVIDER_TOKEN:
            try:
                await context.bot.send_invoice(
                    chat_id=user.id,
                    title="Премиум-подписка на месяц",
                    description="Премиум-колода и 3 бесплатных личных расклада в месяц",
                    payload="premium_card_1month",
                    provider_token=PAYMENT_PROVIDER_TOKEN,
                    currency="RUB",
                    prices=[LabeledPrice("Премиум 1 месяц", PREMIUM_PRICE_RUB * 100)],
                )
            except TelegramError:
                bot.logger.exception("Failed to send card invoice")
                await context.bot.send_message(
                    chat_id=user.id,
                    text="Не удалось создать счёт. Попробуй чуть позже.",
                    reply_markup=bot.MAIN_KEYBOARD,
                )
        else:
            from human_reading import PAYMENT_CARD, PAYMENT_PHONE
            manual_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Я оплатил", callback_data="premium:paid:card")],
                [InlineKeyboardButton("✖ Отмена", callback_data="premium:close")],
            ])
            await context.bot.send_message(
                chat_id=user.id,
                text=(
                    f"💳 <b>Оплата премиума — {PREMIUM_PRICE_RUB} ₽</b>\n\n"
                    f"Карта (нажми чтобы скопировать):\n<pre>{PAYMENT_CARD}</pre>\n"
                    f"СБП по номеру:\n<pre>{PAYMENT_PHONE}</pre>\n"
                    f"Сумма точно: <b>{PREMIUM_PRICE_RUB} ₽</b>\n\n"
                    "После оплаты нажми «Я оплатил» — оператор проверит и активирует подписку."
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=manual_kb,
            )
        return

    if data == "premium:paid:card":
        sender = f"@{user.username}" if user.username else (user.first_name or str(user.id))
        note = (
            f"💠 Заявка на премиум (карта)\n\n"
            f"От: {sender}\nUser ID: {user.id}\n"
            f"Сумма: {PREMIUM_PRICE_RUB} ₽\n\n"
            "ПРОВЕРЬ ПОСТУПЛЕНИЕ."
        )
        confirm_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Подтвердить оплату", callback_data=f"op:premium_confirm:{user.id}")],
            [InlineKeyboardButton("❌ Отклонить", callback_data=f"op:premium_decline:{user.id}")],
        ])
        for admin_id in bot.ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=admin_id, text=note, reply_markup=confirm_kb)
            except TelegramError:
                bot.logger.exception("Failed to notify admin about premium payment chat_id=%s", admin_id)
        await context.bot.send_message(
            chat_id=user.id,
            text="✅ Заявка на премиум получена. После проверки оплаты подписка будет активирована.",
            reply_markup=bot.MAIN_KEYBOARD,
        )
        return

    if data == "premium:year":
        try:
            await query.delete_message()
        except TelegramError:
            pass
        await send_year_rasklad(update, context)
        return

    if data == "premium:pair":
        if is_trial_active(user.id):
            await query.answer("Расклад на пару доступен только в платном премиуме.", show_alert=True)
            return
        try:
            await query.delete_message()
        except TelegramError:
            pass
        context.user_data["state"] = "waiting_pair_name"
        await context.bot.send_message(
            chat_id=user.id,
            text="✌️ Напиши имя человека для расклада на пару:",
            reply_markup=bot.MAIN_KEYBOARD,
        )
        return

    if data == "premium:weekday_menu":
        if is_trial_active(user.id):
            await query.answer("Настройка дня доступна только в платном премиуме.", show_alert=True)
            return
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(d, callback_data=f"weekly_day:{i}")]
            for i, d in enumerate(["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"])
        ])
        await query.edit_message_text("📅 Выбери день для еженедельной руны:", reply_markup=kb)
        return


async def precheckout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.pre_checkout_query.answer(ok=True)


async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    payment = update.message.successful_payment
    if payment.invoice_payload.startswith("premium_"):
        activate_premium(update.effective_user.id)
        await update.message.reply_text(
            "💠 <b>Премиум активирован на 30 дней!</b>\n\n"
            "✅ Доступно:\n"
            "• Премиум-колода\n"
            "• Расклад на год\n"
            "• Расклад на пару\n"
            "• 3 личных расклада в месяц\n"
            "• Настройка дня еженедельной руны",
            parse_mode=ParseMode.HTML,
            reply_markup=build_main_keyboard(update.effective_user.id),
        )


async def operator_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user:
        return
    await query.answer()
    data = query.data or ""

    if data.startswith("op:claim:"):
        request_id = int(data.split(":")[2])
        op = update.effective_user
        try:
            claim_request(request_id, op.id, op.username or str(op.id))
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Взято в работу", callback_data="op:noop")]
            ]))
        except Exception:
            await query.answer("Не удалось взять заявку.", show_alert=True)
        return

    if data.startswith("op:decline:"):
        request_id = int(data.split(":")[2])
        try:
            req = get_request(request_id)
            close_request(request_id)
            if req:
                await context.bot.send_message(
                    chat_id=req["user_id"],
                    text="🕯 Заявка на личный расклад отклонена оператором. Попробуй позже.",
                    reply_markup=bot.MAIN_KEYBOARD,
                )
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Отклонено", callback_data="op:noop")]
            ]))
        except Exception:
            await query.answer("Не удалось отклонить заявку.", show_alert=True)
        return

    if data.startswith("op:premium_confirm:"):
        target_id = int(data.split(":")[2])
        try:
            activate_premium(target_id)
            await context.bot.send_message(
                chat_id=target_id,
                text="💠 <b>Премиум активирован!</b>\n\nОплата подтверждена.",
                parse_mode=ParseMode.HTML,
                reply_markup=build_main_keyboard(target_id),
            )
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Премиум активирован", callback_data="op:noop")]
            ]))
        except Exception:
            await query.answer("Не удалось активировать.", show_alert=True)
        return

    if data.startswith("op:premium_decline:"):
        target_id = int(data.split(":")[2])
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="❌ Оплата не подтверждена. Проверь реквизиты и попробуй снова.",
                reply_markup=bot.MAIN_KEYBOARD,
            )
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Отклонено", callback_data="op:noop")]
            ]))
        except Exception:
            await query.answer("Ошибка.", show_alert=True)
        return


_WEEKDAY_NAMES = {0: "Понедельник", 1: "Вторник", 2: "Среда",
                  3: "Четверг", 4: "Пятница", 5: "Суббота", 6: "Воскресенье"}


async def weekly_day_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Let user choose which day to receive weekly rune+question."""
    if not await bot.ensure_profile_ready(update, context):
        return
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Понедельник", callback_data="weekly_day:0"),
         InlineKeyboardButton("Среда", callback_data="weekly_day:2")],
        [InlineKeyboardButton("Пятница", callback_data="weekly_day:4"),
         InlineKeyboardButton("Воскресенье", callback_data="weekly_day:6")],
    ])
    await update.effective_message.reply_text(
        "🪬 <b>Когда присылать руну недели и вопрос для рефлексии?</b>\n\n"
        "Выбери удобный день:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


async def weekly_day_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user:
        return
    await query.answer()
    try:
        day = int(query.data.split(":")[1])
        from database import set_weekly_question_day
        set_weekly_question_day(update.effective_user.id, day)
    except Exception:
        bot.logger.exception("Failed to set weekly_question_day")
        await query.edit_message_text("Не получилось сохранить. Попробуй ещё раз.")
        return
    day_name = _WEEKDAY_NAMES.get(day, "выбранный день")
    await query.edit_message_text(
        f"✅ Буду присылать руну недели каждый <b>{day_name.lower()}</b>.",
        parse_mode=ParseMode.HTML,
    )


async def weekly_rasklad_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User tapped 'Спросить руны об этом' under weekly question."""
    query = update.callback_query
    if not query or not update.effective_user:
        return
    await query.answer()
    try:
        week = int(query.data.split(":")[1])
        from runes_data import RUNES
        from weekly_questions import rune_of_week, question_for_rune
        weekly_rune = rune_of_week(RUNES, week)
        question = question_for_rune(weekly_rune["key"], week)
    except Exception:
        bot.logger.exception("Failed to get weekly rune for rasklad")
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="Не получилось запустить расклад. Попробуй через меню 🔮 Расклад.",
            reply_markup=bot.MAIN_KEYBOARD,
        )
        return
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except TelegramError:
        pass
    await product_runtime.bot.send_rasklad(update, context, question)


def final_build_application():
    if not bot.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set. Add it in environment variables.")
    bot.init_db()
    init_support_db()
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
    app.add_handler(CommandHandler("activatepremium", activatepremium_command))
    app.add_handler(CommandHandler("claim", claim_command))
    app.add_handler(CommandHandler("answer", answer_command))
    app.add_handler(CommandHandler("subscribe", subscribe_command))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe_command))
    app.add_handler(CommandHandler("pair", pair_rasklad_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("premium", premium_command))
    app.add_handler(CommandHandler("weekday", weekly_day_command))
    app.add_handler(CommandHandler("menu", lambda u, c: u.effective_message.reply_text("Меню открыто.", reply_markup=build_main_keyboard(u.effective_user.id))))
    app.add_handler(CallbackQueryHandler(final_onboarding_callback, pattern=r"^onboarding:"))
    app.add_handler(CallbackQueryHandler(product_runtime.settings_callback, pattern=r"^settings:deck:"))
    app.add_handler(CallbackQueryHandler(weekly_day_callback, pattern=r"^weekly_day:"))
    app.add_handler(CallbackQueryHandler(weekly_rasklad_callback, pattern=r"^weekly_rasklad:"))
    app.add_handler(CallbackQueryHandler(human_reading_payment_callback, pattern=r"^human_reading:"))
    app.add_handler(CallbackQueryHandler(premium_callback, pattern=r"^premium:"))
    app.add_handler(CallbackQueryHandler(operator_action_callback, pattern=r"^op:"))
    app.add_handler(PreCheckoutQueryHandler(precheckout_handler))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))
    app.add_handler(MessageHandler((filters.PHOTO | filters.Document.ALL) & ~filters.COMMAND, operator_media_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, final_text_router))
    app.add_error_handler(bot.error_handler)
    # Daily broadcast job — 09:00 Moscow time every day
    app.job_queue.run_daily(send_daily_rune, time=BROADCAST_TIME, name="daily_rune_broadcast")
    # Weekly reflection question — runs daily at 07:00 UTC, filters by user's preferred day
    from datetime import time as dtime, timezone
    weekly_time = dtime(7, 0, tzinfo=timezone.utc)
    app.job_queue.run_daily(send_weekly_question, time=weekly_time, name="weekly_question")
    # Premium expiry warnings — check daily at 08:00 Moscow (05:00 UTC)
    expiry_time = dtime(5, 0, tzinfo=timezone.utc)
    app.job_queue.run_daily(send_premium_expiry_warnings, time=expiry_time, name="premium_expiry_warnings")
    # Monthly rune — runs daily at 07:00 UTC, acts only on day==1
    monthly_time = dtime(7, 0, tzinfo=timezone.utc)
    app.job_queue.run_daily(send_monthly_rune, time=monthly_time, name="monthly_rune")
    return app


bot.get_rune_image_path = robust_get_rune_image_path
bot.build_application = final_build_application
product_runtime.human_reading_command = human_reading_command
product_runtime.handle_human_request = handle_human_request

if __name__ == "__main__":
    bot.main()
