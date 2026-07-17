import asyncio
import re
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
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
from spread_engine_approved import send_approved_rasklad, spread_page_callback
from human_reading import (
    HUMAN_READING_BUTTON,
    HUMAN_READING_CANCEL_TEXT,
    HUMAN_READING_PAID_PROMPT,
    HUMAN_READING_TEXT,
    PAYMENT_AMOUNT,
    PAYMENT_CARD_DISPLAY,
    PAYMENT_CANCEL_CALLBACK,
    PAYMENT_CONFIRM_CALLBACK,
    PAYMENT_PHONE_DISPLAY,
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

# Explicit runtime composition. This used to happen implicitly in
# sitecustomize.py before the application module was even imported.
product_runtime.configure_bot_runtime()
bot.send_rasklad = send_approved_rasklad

VERSION_MARKER = "RUNA FINAL 2026-05-07-6"

HIDE_KEYBOARD_BUTTON = "🙈 Скрыть меню"


async def _safe_callback_answer(query, *args, **kwargs) -> None:
    """Stop a Telegram button spinner without failing if it was answered already."""
    try:
        await query.answer(*args, **kwargs)
    except TelegramError:
        pass


async def reading_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Restore the full reply keyboard only when the reader asks for it."""
    query = update.callback_query
    if not query or not update.effective_user:
        return
    await query.answer()
    # Give Telegram time to dismiss the inline-button tap before replacing it
    # with the reply keyboard. This prevents the same tap from landing on a
    # newly appeared menu item (most noticeably "Settings" on mobile).
    await asyncio.sleep(0.25)
    await context.bot.send_message(
        chat_id=update.effective_user.id,
        text="Меню открыто.",
        reply_markup=build_main_keyboard(update.effective_user.id),
    )


def _kb(update: Update) -> ReplyKeyboardMarkup:
    """Shortcut: dynamic keyboard for the current user."""
    uid = update.effective_user.id if update.effective_user else 0
    return build_main_keyboard(uid)


def build_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    """Возвращает клавиатуру с учётом premium статуса пользователя."""
    from premium_subscription import get_premium_state
    base = [
        ["🌞 Руна дня", "❓ Вопрос (да/нет)"],
        ["🔮 Расклад", "🕯 Личный расклад"],
    ]
    try:
        premium_active, trial_active = get_premium_state(user_id)
        if premium_active:
            if trial_active:
                base.append(["🗓 Расклад на год", "💠 Премиум"])
                base.append(["⚙️ Настройки"])
            else:
                base.append(["🗓 Расклад на год", "👥 Взаимоотношения"])
                base.append(["💠 Премиум", "⚙️ Настройки"])
        else:
            base.append(["💠 Премиум", "⚙️ Настройки"])
    except Exception:
        base.append(["💠 Премиум", "⚙️ Настройки"])
    base.append(["📜 Значения рун", "ℹ️ Помощь"])
    return ReplyKeyboardMarkup(base, resize_keyboard=True, is_persistent=False)


# bot.py owns the common sending helper; give it the product-aware keyboard
# factory once this module is loaded, avoiding stale reduced keyboards.
bot.MAIN_KEYBOARD_FACTORY = build_main_keyboard
ALLOWED_OPERATOR_USERNAMES = {"mrgrief", "richstewardess"}
PREMIUM_DIR_CANDIDATES = ["premium", "Premium", "Премиум", "премиум"]
IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp"]
REQUEST_ID_RE = re.compile(r"заявка\s*#\s*(\d+)", re.IGNORECASE)


def is_operator_chat(update: Update) -> bool:
    chat = update.effective_chat
    return bool(chat and chat.id in bot.ADMIN_IDS and chat.type != "private")


def is_operator_reply(update: Update) -> bool:
    """Accept request replies in an operator group or an admin's private chat.

    A private admin chat must only be intercepted when the message is an
    actual reply to a request notification. Otherwise the admin must still be
    able to use the bot as an ordinary user.
    """
    if extract_request_id_from_reply(update) is None:
        return False
    return is_operator_chat(update) or is_authorized_operator(update)


def is_authorized_operator(update: Update) -> bool:
    user = update.effective_user
    if not user:
        return False
    if user.id in bot.ADMIN_IDS:
        return True
    if user.username and user.username.lower() in ALLOWED_OPERATOR_USERNAMES:
        return True
    try:
        return user.id in set(list_operator_ids())
    except SupportRequestError:
        bot.logger.exception("Failed to load registered operators")
        return False


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
        profile = await asyncio.to_thread(bot.get_user_profile, update.effective_user.id)
        if not profile or profile.get("preferred_name") != name:
            await asyncio.to_thread(bot.ensure_user, update.effective_user.id, name)
            profile = await asyncio.to_thread(bot.get_user_profile, update.effective_user.id)
        if not profile or not profile.get("palette"):
            await asyncio.to_thread(bot.start_onboarding, update.effective_user.id)
            await update.effective_message.reply_text(product_runtime.build_onboarding_question(1, name), reply_markup=product_runtime.onboarding_keyboard(1))
            return
    except bot.DatabaseError:
        bot.logger.exception("Failed to start final onboarding")
        await update.effective_message.reply_text("Что-то пошло не так. Попробуй ещё раз через минуту.", reply_markup=_kb(update))
        return
    await update.effective_message.reply_text(f"{name}, всё готово. С чего начнём?", reply_markup=_kb(update))


async def final_onboarding_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user:
        return
    await query.answer()
    try:
        _, step_raw, answer = query.data.split(":", 2)
        int(step_raw)
        result = await asyncio.to_thread(
            bot.save_onboarding_answer,
            update.effective_user.id,
            answer,
            len(bot.ONBOARDING_QUESTIONS),
        )
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
                "📜 <b>Значения рун</b> — отдельный справочник\n"
                "⚙️ <b>Настройки</b> — сменить колоду\n\n"
                "Можно нажать кнопку ниже."
            ),
            reply_markup=_kb(update),
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


def premium_card_payment_text() -> str:
    return (
        f"💳 <b>Оплата премиума — {PREMIUM_PRICE_RUB} ₽</b>\n\n"
        f"Карта: <code>{PAYMENT_CARD_DISPLAY}</code>\n"
        f"СБП: <code>{PAYMENT_PHONE_DISPLAY}</code>\n\n"
        f"Сумма точно: <b>{PREMIUM_PRICE_RUB} ₽</b>\n\n"
        "После оплаты нажми «Я оплатил» — оператор проверит и активирует подписку."
    )


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
            reply_markup=_kb(update),
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
                reply_markup=ReplyKeyboardRemove(),
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
            reply_markup=_kb(update),
        )
        return
    if query.data == PAYMENT_CONFIRM_CALLBACK:
        if not context.user_data.get("human_reading_payment_pending"):
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text="Нажми «🕯 Личный расклад» в меню, чтобы оформить новую заявку.",
                reply_markup=_kb(update),
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
            reply_markup=ReplyKeyboardRemove(),
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
                reply_markup=build_main_keyboard(user_id),
            )
        elif message.document:
            caption = (message.caption or "").strip() or None
            await context.bot.send_document(
                chat_id=user_id,
                document=message.document.file_id,
                caption=caption,
                reply_markup=build_main_keyboard(user_id),
            )
        elif message.text:
            await context.bot.send_message(
                chat_id=user_id,
                text=message.text.strip(),
                reply_markup=build_main_keyboard(user_id),
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
    if not is_operator_reply(update):
        return
    await handle_operator_reply(update, context)


async def final_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.effective_message.text or "").strip()
    state = context.user_data.get("state")
    user_id = update.effective_user.id if update.effective_user else 0
    if is_operator_reply(update):
        await handle_operator_reply(update, context)
        return
    if text == HIDE_KEYBOARD_BUTTON:
        await update.effective_message.reply_text(
            "Меню скрыто. Напиши любое сообщение или /menu чтобы вернуть его.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    if text in {"/menu", "📲 Показать меню", "↩ Меню"}:
        await update.effective_message.reply_text(
            "Меню открыто.", reply_markup=build_main_keyboard(user_id)
        )
        return
    if text == "🌞 Руна дня":
        await product_runtime.product_runa_command(update, context)
        return
    if text == "📜 Значения рун":
        from runes_data import RUNES
        rune_pairs = [(rune["key"], rune["name"]) for rune in RUNES]
        await update.effective_message.reply_text(
            "📜 <b>Традиционные значения рун</b>\n\n"
            "Это отдельный справочник по символике и происхождению рун. "
            "Он не заменяет и не уточняет полученный расклад.\n\n"
            "Выбери руну:",
            reply_markup=product_runtime.rune_info_keyboard(rune_pairs),
            parse_mode="HTML",
        )
        return
    if text in {"❓ Вопрос", "❓ Задать вопрос", "❓ Вопрос (да/нет)"}:
        context.user_data["state"] = bot.STATE_WAITING_ASK
        await update.effective_message.reply_text(
            "❓ <b>Напиши свой вопрос</b> одним сообщением.\n\n"
            "Лучше о ситуации, решении или отношениях, на которые ты можешь повлиять.",
            reply_markup=ReplyKeyboardRemove() if bot.is_private(update) else None,
            parse_mode="HTML",
        )
        return
    if text == "🔮 Расклад":
        context.user_data["state"] = bot.STATE_WAITING_RASKLAD
        await update.effective_message.reply_text(
            "🔮 Напиши вопрос — раскину три карты на ситуацию.",
            reply_markup=ReplyKeyboardRemove() if bot.is_private(update) else None,
        )
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
    if text in {"👥 Взаимоотношения", "💕 Взаимоотношения"}:
        if is_trial_active(user_id):
            await update.effective_message.reply_text(
                "👥 Расклады на взаимоотношения доступны только в платном премиуме.",
                reply_markup=build_main_keyboard(user_id),
            )
            return
        context.user_data["state"] = "waiting_relationship_name"
        await update.effective_message.reply_text(
            "👥 <b>Взаимоотношения</b>\n\n"
            "Три карты: твоя энергия, энергия другого человека и то, что между вами.\n\n"
            "Напиши имя или описание человека:\n"
            "<i>Анна (подруга) · Андрей (коллега) · мой парень</i>",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="HTML"
        )
        return
    if text == "✌️ Расклад на пару":  # backward compatibility
        if is_trial_active(user_id):
            await update.effective_message.reply_text(
                "👥 Расклады на взаимоотношения доступны только в платном премиуме.",
                reply_markup=build_main_keyboard(user_id),
            )
            return
        context.user_data["state"] = "waiting_relationship_name"
        await update.effective_message.reply_text(
            "👥 <b>Взаимоотношения</b>\n\n"
            "Три карты: твоя энергия, энергия другого человека и то, что между вами.\n\n"
            "Напиши имя или описание человека:\n"
            "<i>Анна (подруга) · Андрей (коллега) · мой парень</i>",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="HTML"
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
    if state == "waiting_relationship_name":
        context.user_data.pop("state", None)
        from relationship_rasklad import send_relationship_type_choice
        await send_relationship_type_choice(update, context, text)
        return
    if state == bot.STATE_WAITING_ASK:
        context.user_data.pop("state", None)
        await product_runtime.product_send_one_rune_answer(update, context, text)
        return
    if state == bot.STATE_WAITING_RASKLAD:
        context.user_data.pop("state", None)
        await send_approved_rasklad(update, context, text)
        return
    await update.effective_message.reply_text("Выбери действие на клавиатуре. Или напиши /help, если потерялся.", reply_markup=_kb(update) if bot.is_private(update) else bot.private_link_markup(context))


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
            reply_markup=_kb(update),
        )
    except Exception:
        pass


async def whoami_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return
    await update.effective_message.reply_text(f"User ID: {user.id}\nChat ID: {chat.id}\nUsername: @{user.username}" if user.username else f"User ID: {user.id}\nChat ID: {chat.id}")


async def where_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show whether the current chat receives manual payment requests."""
    chat = update.effective_chat
    if not chat:
        return
    title = getattr(chat, "title", None) or "личный чат"
    connected = chat.id in bot.ADMIN_IDS
    status = "✅ подключён" if connected else "❌ не подключён"
    await update.effective_message.reply_text(
        f"Чат: {title}\nChat ID: {chat.id}\nПриём заявок на оплату: {status}\n\n"
        "Чтобы подключить этот чат, добавь его Chat ID в ADMIN_IDS сервиса Cloud Run."
    )


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
        await context.bot.send_message(chat_id=request["user_id"], text=answer_text, reply_markup=build_main_keyboard(request["user_id"]))
        close_request(request_id)
    except (TelegramError, SupportRequestError):
        await update.effective_message.reply_text("Не получилось отправить ответ пользователю.")
        return
    await update.effective_message.reply_text(f"Ответ по заявке #{request_id} отправлен.")


def _premium_features_keyboard(on_trial: bool) -> InlineKeyboardMarkup:
    if on_trial:
        # Trial: year reading is in main keyboard, but pair/weekday need upgrade
        buttons = [
            [InlineKeyboardButton("💳 Оформить полный премиум (Stars)", callback_data="premium:buy:stars")],
            [InlineKeyboardButton("💳 Оплатить картой", callback_data="premium:buy:card")],
        ]
    else:
        # Paid: year reading and pair are already in the main keyboard —
        # only show weekday setting here (it has no dedicated button in main keyboard)
        buttons = [
            [InlineKeyboardButton("📅 Настройка дня руны недели", callback_data="premium:weekday_menu")],
        ]
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
        if on_trial:
            body = (
                f"💠 <b>Пробный период активен до {exp_formatted}</b>\n\n"
                "✅ Доступно: премиум-колода, расклад на год\n"
                "❌ Только в платном: расклад на взаимоотношения, личные расклады, еженедельный вопрос\n\n"
                "Хочешь всё — оформи полный премиум:"
            )
        else:
            body = (
                f"💠 <b>Премиум активен до {exp_formatted}</b>\n\n"
                f"Бесплатных личных раскладов в этом месяце: <b>{free_left}</b>\n\n"
                "Расклад на год и расклад на взаимоотношения — в кнопках меню ниже."
            )
        await message.reply_text(
            body,
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
    user = update.effective_user
    data = query.data or ""

    if data == "premium:close":
        await query.answer()
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
        await query.answer()
        try:
            expires_at = activate_trial(user.id)
        except Exception:
            bot.logger.exception("Failed to activate trial for user_id=%s", user.id)
            await context.bot.send_message(
                chat_id=user.id,
                text="Не удалось активировать пробный период. Попробуй позже.",
                reply_markup=_kb(update),
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
                "• Расклад на взаимоотношения\n"
                "• 3 личных расклада в месяц\n"
                "• Еженедельный вопрос для рефлексии"
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=build_main_keyboard(user.id),
        )
        return

    if data == "premium:buy:stars":
        await query.answer()
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
                reply_markup=_kb(update),
            )
        return

    if data == "premium:buy:card":
        await query.answer()
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
                    reply_markup=_kb(update),
                )
        else:
            manual_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Я оплатил", callback_data="premium:paid:card")],
                [InlineKeyboardButton("✖ Отмена", callback_data="premium:close")],
            ])
            await context.bot.send_message(
                chat_id=user.id,
                text=premium_card_payment_text(),
                parse_mode=ParseMode.HTML,
                reply_markup=manual_kb,
            )
        return

    if data == "premium:paid:card":
        await query.answer()
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
        delivered_to = []
        for admin_id in bot.ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=admin_id, text=note, reply_markup=confirm_kb)
                delivered_to.append(admin_id)
            except TelegramError:
                bot.logger.exception("Failed to notify admin about premium payment chat_id=%s", admin_id)
        if delivered_to:
            response = "✅ Заявка на премиум получена. После проверки оплаты подписка будет активирована."
        else:
            response = (
                "⚠️ Оплата отмечена, но заявка не дошла оператору. "
                "Напиши в поддержку и не нажимай оплату повторно."
            )
        await context.bot.send_message(chat_id=user.id, text=response, reply_markup=_kb(update))
        return

    if data == "premium:year":
        await query.answer()
        try:
            await query.delete_message()
        except TelegramError:
            pass
        await send_year_rasklad(update, context)
        return

    if data == "premium:pair":
        if is_trial_active(user.id):
            await query.answer("Расклад на взаимоотношения доступен только в платном премиуме.", show_alert=True)
            return
        await query.answer()
        try:
            await query.delete_message()
        except TelegramError:
            pass
        context.user_data["state"] = "waiting_pair_name"
        await context.bot.send_message(
            chat_id=user.id,
            text="👥 Напиши имя или описание человека:\n<i>Анна (подруга) · Андрей (коллега) · мой парень</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    if data == "premium:weekday_menu":
        if is_trial_active(user.id):
            await query.answer("Настройка дня доступна только в платном премиуме.", show_alert=True)
            return
        await query.answer()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(d, callback_data=f"weekly_day:{i}")]
            for i, d in enumerate(["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"])
        ])
        await query.edit_message_text("📅 Выбери день для еженедельной руны:", reply_markup=kb)
        return

    await query.answer("Эта кнопка устарела. Открой раздел «Премиум» заново.", show_alert=True)


async def precheckout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.pre_checkout_query
    if not query:
        return
    if not _valid_premium_payment(query.invoice_payload, query.currency, query.total_amount):
        await query.answer(ok=False, error_message="Параметры платежа не совпадают со счётом. Создай новый счёт в меню премиума.")
        return
    await query.answer(ok=True)


def _valid_premium_payment(payload: str, currency: str, total_amount: int) -> bool:
    expected = {
        "premium_stars_1month": ("XTR", PREMIUM_PRICE_STARS),
        "premium_card_1month": ("RUB", PREMIUM_PRICE_RUB * 100),
    }
    return expected.get(payload) == (currency, total_amount)


async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    payment = update.message.successful_payment
    if _valid_premium_payment(payment.invoice_payload, payment.currency, payment.total_amount):
        activate_premium(update.effective_user.id)
        await update.message.reply_text(
            "💠 <b>Премиум активирован на месяц!</b>\n\n"
            "✅ Доступно:\n"
            "• Премиум-колода\n"
            "• Расклад на год\n"
            "• Расклад на взаимоотношения\n"
            "• 3 личных расклада в месяц\n"
            "• Еженедельный вопрос для рефлексии",
            parse_mode=ParseMode.HTML,
            reply_markup=build_main_keyboard(update.effective_user.id),
        )


async def operator_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user:
        return
    if not is_authorized_operator(update):
        await query.answer("Это действие доступно только оператору.", show_alert=True)
        return
    await query.answer()
    data = query.data or ""

    if data == "op:noop":
        return

    if data.startswith("op:claim:"):
        request_id = int(data.split(":")[2])
        op = update.effective_user
        try:
            claim_request(request_id, op.id, op.username or str(op.id))
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Взято в работу", callback_data="op:noop")]
            ]))
        except Exception:
            bot.logger.exception("Failed to claim personal reading request")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Не удалось взять заявку. Обнови сообщение и попробуй ещё раз.",
            )
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
                    reply_markup=_kb(update),
                )
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Отклонено", callback_data="op:noop")]
            ]))
        except Exception:
            bot.logger.exception("Failed to decline personal reading request")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Не удалось отклонить заявку. Попробуй ещё раз.",
            )
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
            bot.logger.exception("Failed to confirm premium payment")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Не удалось активировать премиум. Попробуй ещё раз.",
            )
        return

    if data.startswith("op:premium_decline:"):
        target_id = int(data.split(":")[2])
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="❌ Оплата не подтверждена. Проверь реквизиты и попробуй снова.",
                reply_markup=_kb(update),
            )
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Отклонено", callback_data="op:noop")]
            ]))
        except Exception:
            bot.logger.exception("Failed to decline premium payment")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Не удалось отклонить оплату. Попробуй ещё раз.",
            )
        return

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Эта кнопка устарела. Открой актуальную заявку.",
    )


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
            reply_markup=_kb(update),
        )
        return
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except TelegramError:
        pass
    await send_approved_rasklad(update, context, question)


async def relationship_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle relationship type selection (personal vs business)."""
    query = update.callback_query
    if not query or not update.effective_user:
        return

    try:
        parts = query.data.split(":", 2)
        if parts[0] == "rel_type" and len(parts) >= 2:
            rel_type = parts[1]  # personal or business
            if rel_type not in {"personal", "business"}:
                await query.answer("Этот тип расклада больше недоступен.", show_alert=True)
                return
            person_name = (
                parts[2]
                if len(parts) == 3
                else context.user_data.get("relationship_person", "")
            )
            if not person_name:
                await query.answer("Напиши имя ещё раз.", show_alert=True)
                return

            await query.answer()
            await query.edit_message_text(f"⏳ Выбираю карты для {person_name}...")

            from relationship_rasklad import _build_relationship_text
            await _build_relationship_text(update, context, person_name, rel_type)
    except Exception:
        bot.logger.exception("Failed to handle relationship type callback")
        await _safe_callback_answer(query)
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="Не получилось запустить расклад. Попробуй выбрать тип ещё раз.",
        )


async def trigger_question_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle trigger question selection."""
    query = update.callback_query
    if not query or not update.effective_user:
        return

    try:
        data = query.data
        if data.startswith("trigger_q:"):
            question = data.split(":", 1)[1]
            if question == "own":
                await query.answer()
                await query.edit_message_text("❓ Напиши свой вопрос — отвечу одной картой.")
                context.user_data["state"] = bot.STATE_WAITING_ASK
            elif question == "А ты говоришь правду?":
                # Special handling for truth question - show philosophical answer
                await query.answer()

                from philosophical_answers import get_truth_answer
                from rune_text_repository import orientation_label, yes_no_draw

                # Use the same polarity rule as the rest of the yes/no flow;
                # symmetric runes remain visually upright.
                from runes_data import RUNES
                rune = product_runtime.draw_yes_no_rune(RUNES)
                orientation, answer_kind = yes_no_draw(rune["key"])
                palette = bot.get_user_palette(update)
                image_path = bot.get_rune_image_path(rune, palette)

                is_yes = answer_kind == "yes"
                philosophical_answer = get_truth_answer(is_yes)

                message_text = (
                    f"❓ <b>{question}</b>\n\n{philosophical_answer}\n\n"
                    f"<i>Руна: {rune['name']} · {orientation_label(orientation, rune['key'])}</i>"
                )

                await query.edit_message_text(message_text, parse_mode="HTML")
                if image_path:
                    await bot.send_cached_photo(
                        context.bot.send_photo,
                        image_path,
                        chat_id=update.effective_user.id,
                    )

                context.user_data.pop("state", None)
            else:
                # Use regular trigger question
                await query.answer()
                await query.edit_message_text(f"❓ {question}\n\n⏳ Выбираю карту...", parse_mode="HTML")
                context.user_data.pop("state", None)
                await product_runtime.product_send_one_rune_answer(update, context, question)
    except Exception:
        bot.logger.exception("Failed to handle trigger question callback")
        await _safe_callback_answer(query)
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="Не получилось обработать этот вопрос. Попробуй через пункт «Вопрос (да/нет)».",
            reply_markup=build_main_keyboard(update.effective_user.id),
        )


async def rune_info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show a traditional/etymological meaning selected in the reference."""
    query = update.callback_query
    if not query or not update.effective_user:
        return
    try:
        await query.answer()
        _, rune_key = query.data.split(":", 1)
        from runes_data import get_rune_by_key
        from rune_traditional import get_traditional_text
        rune = get_rune_by_key(rune_key)
        rune_name = rune["name"] if rune else rune_key
        text = get_traditional_text(rune_key, rune_name)
        await query.message.reply_text(text, parse_mode="HTML")
    except Exception:
        bot.logger.exception("Failed to handle rune_info callback")
        await _safe_callback_answer(query)
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="Не получилось показать значение руны. Открой справочник заново.",
        )


async def year_rasklad_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle year rasklad interactions: viewing rune details and navigating between months."""
    query = update.callback_query
    if not query or not update.effective_user:
        return

    try:
        parts = query.data.split(":")
        if parts[0] == "year_rune":
            # Format: year_rune:user_id:year:month_num
            user_id = int(parts[1])
            year = int(parts[2])
            month_num = int(parts[3])
            if user_id != update.effective_user.id:
                await query.answer("Это не твой расклад.", show_alert=True)
                return
            from year_rasklad import send_rune_year_details
            await send_rune_year_details(update, context, user_id, year, month_num)
        elif parts[0] == "year_rasklad_back":
            # Format: year_rasklad_back:user_id:year
            user_id = int(parts[1])
            year = int(parts[2])
            if user_id != update.effective_user.id:
                await query.answer("Это не твой расклад.", show_alert=True)
                return
            from year_rasklad import send_year_rasklad_from_callback
            await send_year_rasklad_from_callback(update, context, user_id, year)
        else:
            await query.answer("Эта кнопка устарела.", show_alert=True)
    except Exception:
        bot.logger.exception("Failed to handle year rasklad callback")
        await _safe_callback_answer(query)
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="Не получилось открыть месяц. Запусти расклад на год заново.",
            reply_markup=build_main_keyboard(update.effective_user.id),
        )


async def show_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
        return
    await update.effective_message.reply_text(
        "Меню открыто.",
        reply_markup=build_main_keyboard(update.effective_user.id),
    )


def final_build_application():
    if not bot.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set. Add it in environment variables.")
    from neon_persistence import NeonPersistence

    app = (
        bot.Application.builder()
        .token(bot.BOT_TOKEN)
        .persistence(NeonPersistence())
        .post_init(bot.post_init)
        .build()
    )

    async def warm_databases() -> None:
        """Warm Neon after the HTTP server starts, not on the cold-start path."""
        import asyncio
        try:
            await asyncio.to_thread(bot.init_db)
            await asyncio.to_thread(init_support_db)
        except Exception:
            bot.logger.exception("Background database warmup failed")

    app.bot_data["startup_warmup"] = warm_databases

    async def scheduled_maintenance() -> str:
        """Run all daily maintenance from one authenticated Cloud Scheduler call."""
        from types import SimpleNamespace

        # Each recipient is claimed independently in daily_broadcast. This
        # lets a retry resume after a partial failure without duplicating
        # messages that were already delivered.
        job_context = SimpleNamespace(bot=app.bot)
        await send_daily_rune(job_context)
        await send_weekly_question(job_context)
        await send_premium_expiry_warnings(job_context)
        await send_monthly_rune(job_context)
        return "OK"

    app.bot_data["scheduled_maintenance"] = scheduled_maintenance
    app.add_handler(CommandHandler("start", final_start_command))
    app.add_handler(CommandHandler("help", product_runtime.bot.help_command))
    app.add_handler(CommandHandler("profile", product_runtime.bot.profile_command))
    app.add_handler(CommandHandler("check_decks", product_runtime.bot.check_decks_command))
    app.add_handler(CommandHandler("runa", product_runtime.product_runa_command))
    app.add_handler(CommandHandler("ask", product_runtime.bot.ask_command))
    app.add_handler(CommandHandler("rasklad", product_runtime.bot.rasklad_command))
    app.add_handler(CommandHandler("operator", operator_command))
    app.add_handler(CommandHandler("whoami", whoami_command))
    app.add_handler(CommandHandler("where_admin", where_admin_command))
    app.add_handler(CommandHandler("activatepremium", activatepremium_command))
    app.add_handler(CommandHandler("claim", claim_command))
    app.add_handler(CommandHandler("answer", answer_command))
    app.add_handler(CommandHandler("subscribe", subscribe_command))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe_command))
    app.add_handler(CommandHandler("pair", pair_rasklad_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("premium", premium_command))
    app.add_handler(CommandHandler("weekday", weekly_day_command))
    app.add_handler(CommandHandler("menu", show_menu_command))
    app.add_handler(CallbackQueryHandler(final_onboarding_callback, pattern=r"^onboarding:"))
    app.add_handler(CallbackQueryHandler(product_runtime.settings_callback, pattern=r"^settings:deck:"))
    app.add_handler(CallbackQueryHandler(spread_page_callback, pattern=r"^spread_page:"))
    app.add_handler(CallbackQueryHandler(reading_menu_callback, pattern=r"^reading:menu$"))
    app.add_handler(CallbackQueryHandler(trigger_question_callback, pattern=r"^trigger_q:"))
    app.add_handler(CallbackQueryHandler(rune_info_callback, pattern=r"^rune_info:"))
    app.add_handler(CallbackQueryHandler(weekly_day_callback, pattern=r"^weekly_day:"))
    app.add_handler(CallbackQueryHandler(weekly_rasklad_callback, pattern=r"^weekly_rasklad:"))
    app.add_handler(CallbackQueryHandler(year_rasklad_callback, pattern=r"^year_rune:|^year_rasklad_back:"))
    app.add_handler(CallbackQueryHandler(relationship_type_callback, pattern=r"^rel_type:"))
    app.add_handler(CallbackQueryHandler(human_reading_payment_callback, pattern=r"^human_reading:"))
    app.add_handler(CallbackQueryHandler(premium_callback, pattern=r"^premium:"))
    app.add_handler(CallbackQueryHandler(operator_action_callback, pattern=r"^op:"))
    app.add_handler(PreCheckoutQueryHandler(precheckout_handler))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))
    app.add_handler(MessageHandler((filters.PHOTO | filters.Document.ALL) & ~filters.COMMAND, operator_media_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, final_text_router))
    app.add_error_handler(bot.error_handler)
    if not bot.SCHEDULER_SECRET:
        # Local/polling fallback. In Cloud Run, configure SCHEDULER_SECRET and
        # invoke /tasks/scheduled so work happens inside a billable request.
        app.job_queue.run_daily(send_daily_rune, time=BROADCAST_TIME, name="daily_rune_broadcast")
        from datetime import time as dtime, timezone
        weekly_time = dtime(7, 0, tzinfo=timezone.utc)
        app.job_queue.run_daily(send_weekly_question, time=weekly_time, name="weekly_question")
        expiry_time = dtime(5, 0, tzinfo=timezone.utc)
        app.job_queue.run_daily(send_premium_expiry_warnings, time=expiry_time, name="premium_expiry_warnings")
        monthly_time = dtime(7, 0, tzinfo=timezone.utc)
        app.job_queue.run_daily(send_monthly_rune, time=monthly_time, name="monthly_rune")
    return app


bot.build_application = final_build_application
product_runtime.human_reading_command = human_reading_command
product_runtime.handle_human_request = handle_human_request

if __name__ == "__main__":
    bot.main()
