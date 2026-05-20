"""Daily broadcast: sends rune-of-the-day to every subscribed user.

Registered in product_runtime_final.py via JobQueue.
Default send time: 09:00 Moscow time (UTC+3 = UTC 06:00).
Users can opt out with /unsubscribe and back in with /subscribe.
"""

import logging
from datetime import date, time, timezone, timedelta

from telegram import Bot
from telegram.error import Forbidden, TelegramError
from telegram.ext import ContextTypes

import bot as _bot
from database import (
    DatabaseError,
    get_broadcast_users,
    get_or_create_daily_card,
    set_broadcast_enabled,
)
from lunar_calendar import moon_phase_today
from rune_text_repository import get_daily_text
from runes_data import RUNES, get_rune_by_name
from weekly_questions import question_of_week

logger = logging.getLogger(__name__)

# 09:00 Moscow time = 06:00 UTC
BROADCAST_TIME = time(6, 0, tzinfo=timezone.utc)
MOSCOW_TZ = timezone(timedelta(hours=3))


async def send_daily_rune(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback: send today's rune to all subscribed users."""
    today = date.today().isoformat()
    try:
        users = get_broadcast_users(_bot.DB_PATH)
    except DatabaseError:
        logger.exception("Failed to load broadcast users")
        return

    logger.info("Daily broadcast: sending to %d users", len(users))
    sent = blocked = errors = 0

    for user in users:
        user_id = user["user_id"]
        name = user["preferred_name"] or "друг"
        palette = user["palette"] or "light"

        try:
            rune_name, orientation = get_or_create_daily_card(
                _bot.DB_PATH, user_id, today, RUNES
            )
            rune = get_rune_by_name(rune_name)
            image_path = _bot.get_rune_image_path(rune, palette)
            day_text = get_daily_text(rune["key"], palette, orientation)
        except (DatabaseError, KeyError):
            logger.exception("Failed to build rune for user_id=%s", user_id)
            errors += 1
            continue

        palette_icon = {"light": "🌕", "dark": "🌑", "premium": "💠"}.get(palette, "🌕")
        orientation_label = "перевёрнутое" if orientation == "rev" else "прямое"
        moon = moon_phase_today()
        text = (
            f"{palette_icon} <b>{name}, руна дня</b>\n\n"
            f"<b>{rune['name']}</b> · {orientation_label}\n\n"
            f"{day_text}\n\n"
            f"{moon['emoji']} {moon['phase_name']} — {moon['description']}"
        )

        try:
            if image_path:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=open(image_path, "rb"),
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=_bot.MAIN_KEYBOARD,
                )
            else:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=_bot.MAIN_KEYBOARD,
                )
            sent += 1
        except Forbidden:
            # User blocked the bot — silently disable their broadcast
            logger.info("User %s blocked bot, disabling broadcast", user_id)
            try:
                set_broadcast_enabled(_bot.DB_PATH, user_id, False)
            except DatabaseError:
                pass
            blocked += 1
        except TelegramError:
            logger.exception("Failed to send broadcast to user_id=%s", user_id)
            errors += 1

    logger.info(
        "Daily broadcast done: sent=%d blocked=%d errors=%d",
        sent, blocked, errors,
    )


async def send_weekly_question(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback: send weekly reflection question to all subscribed users."""
    try:
        users = get_broadcast_users(_bot.DB_PATH)
    except DatabaseError:
        logger.exception("Failed to load broadcast users for weekly question")
        return

    question = question_of_week()
    logger.info("Weekly question broadcast: sending to %d users", len(users))
    sent = blocked = errors = 0

    for user in users:
        user_id = user["user_id"]
        name = user["preferred_name"] or "друг"
        text = (
            f"🪬 <b>{name}, вопрос недели</b>\n\n"
            f"{question}\n\n"
            f"<i>Можно записать ответ в заметки, а можно спросить руны — 🔮 Расклад в меню.</i>"
        )
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode="HTML",
                reply_markup=_bot.MAIN_KEYBOARD,
            )
            sent += 1
        except Forbidden:
            try:
                set_broadcast_enabled(_bot.DB_PATH, user_id, False)
            except DatabaseError:
                pass
            blocked += 1
        except TelegramError:
            logger.exception("Failed to send weekly question to user_id=%s", user_id)
            errors += 1

    logger.info(
        "Weekly question done: sent=%d blocked=%d errors=%d",
        sent, blocked, errors,
    )


async def subscribe_command(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enable daily broadcast for the user."""
    if not update.effective_user or not update.effective_message:
        return
    try:
        set_broadcast_enabled(_bot.DB_PATH, update.effective_user.id, True)
    except DatabaseError:
        await update.effective_message.reply_text(
            "Не получилось включить рассылку. Попробуй позже.",
            reply_markup=_bot.MAIN_KEYBOARD,
        )
        return
    await update.effective_message.reply_text(
        "🌞 Рассылка включена. Каждое утро в 9:00 буду присылать тебе руну дня.",
        reply_markup=_bot.MAIN_KEYBOARD,
    )


async def unsubscribe_command(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disable daily broadcast for the user."""
    if not update.effective_user or not update.effective_message:
        return
    try:
        set_broadcast_enabled(_bot.DB_PATH, update.effective_user.id, False)
    except DatabaseError:
        await update.effective_message.reply_text(
            "Не получилось отключить рассылку. Попробуй позже.",
            reply_markup=_bot.MAIN_KEYBOARD,
        )
        return
    await update.effective_message.reply_text(
        "Рассылка отключена. Чтобы снова получать руну дня — напиши /subscribe.",
        reply_markup=_bot.MAIN_KEYBOARD,
    )
