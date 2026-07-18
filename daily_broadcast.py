"""Daily broadcast: sends rune-of-the-day to every subscribed user.

Registered in product_runtime_final.py via JobQueue.
Default send time: 09:00 Moscow time (UTC+3 = UTC 06:00).
Users can opt out with /unsubscribe and back in with /subscribe.
"""

import asyncio
import logging
from datetime import date, time, timezone, timedelta

from telegram.error import Forbidden, TelegramError
from telegram.ext import ContextTypes

from reading_format import reading_title, rune_block

import bot as _bot
from database import (
    DatabaseError,
    claim_scheduled_delivery,
    finish_scheduled_delivery,
    get_broadcast_users,
    get_expiring_premium_users,
    get_or_create_daily_card,
    get_streak,
    set_broadcast_enabled,
)
from runes_data import RUNES, get_rune_by_name
from rune_text_repository import orientation_label
from weekly_questions import question_for_rune, rune_of_week

logger = logging.getLogger(__name__)

# 09:00 Moscow time = 06:00 UTC
BROADCAST_TIME = time(6, 0, tzinfo=timezone.utc)
MOSCOW_TZ = timezone(timedelta(hours=3))


async def _claim_delivery(kind: str, delivery_date: str, user_id: int) -> bool:
    try:
        return await asyncio.to_thread(claim_scheduled_delivery, kind, delivery_date, user_id)
    except DatabaseError:
        logger.exception("Failed to claim %s delivery for user_id=%s", kind, user_id)
        return False


async def _finish_delivery(kind: str, delivery_date: str, user_id: int, success: bool) -> None:
    try:
        await asyncio.to_thread(finish_scheduled_delivery, kind, delivery_date, user_id, success)
    except DatabaseError:
        logger.exception("Failed to finish %s delivery for user_id=%s", kind, user_id)


async def send_daily_rune(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback: send today's rune to all subscribed users."""
    today = date.today().isoformat()
    try:
        users = await asyncio.to_thread(get_broadcast_users)
    except DatabaseError:
        logger.exception("Failed to load broadcast users")
        return

    logger.info("Daily broadcast: sending to %d users", len(users))
    sent = blocked = errors = 0

    for user in users:
        user_id = user["user_id"]
        if not await _claim_delivery("daily-rune", today, user_id):
            continue
        name = user["preferred_name"] or "друг"
        palette = user["palette"] or "light"

        try:
            rune_name, orientation = await asyncio.to_thread(
                get_or_create_daily_card, user_id, today, RUNES
            )
            rune = get_rune_by_name(rune_name)
            image_path = _bot.get_rune_image_path(rune, palette)
        except (DatabaseError, KeyError):
            logger.exception("Failed to build rune for user_id=%s", user_id)
            errors += 1
            await _finish_delivery("daily-rune", today, user_id, False)
            continue

        position_label = orientation_label(orientation, rune["key"])
        if image_path:
            from rune_collage import build_single_rune_card
            image_path = await asyncio.to_thread(
                build_single_rune_card, image_path, palette, position_label
            )
        try:
            streak = await asyncio.to_thread(get_streak, user_id)
        except Exception:
            streak = 0
        from product_runtime import build_daily_card_text
        text = build_daily_card_text(name, palette, rune, orientation, today, streak)

        try:
            from telegram import ReplyKeyboardRemove
            if image_path:
                # One compact media message keeps the client at the beginning
                # of the reading instead of below a separate photo.
                await _bot.send_cached_photo(
                    context.bot.send_photo,
                    image_path,
                    chat_id=user_id,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=ReplyKeyboardRemove(),
                )
            else:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=ReplyKeyboardRemove(),
                )
            sent += 1
            await _finish_delivery("daily-rune", today, user_id, True)
        except Forbidden:
            # User blocked the bot — silently disable their broadcast
            logger.info("User %s blocked bot, disabling broadcast", user_id)
            try:
                await asyncio.to_thread(set_broadcast_enabled, user_id, False)
            except DatabaseError:
                pass
            blocked += 1
            await _finish_delivery("daily-rune", today, user_id, True)
        except TelegramError:
            logger.exception("Failed to send broadcast to user_id=%s", user_id)
            errors += 1
            await _finish_delivery("daily-rune", today, user_id, False)

    logger.info(
        "Daily broadcast done: sent=%d blocked=%d errors=%d",
        sent, blocked, errors,
    )


async def send_weekly_question(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback: send weekly rune + reflection question to premium subscribers.

    Runs daily; each user has a preferred weekday (weekly_question_day, 0=Mon…6=Sun).
    Only sends to users whose preferred day matches today.
    """
    from datetime import date as _date
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from runes_data import RUNES

    today = _date.today()
    today_str = today.isoformat()
    today_weekday = today.weekday()  # 0=Mon … 6=Sun
    week = today.isocalendar()[1]

    try:
        users = await asyncio.to_thread(get_broadcast_users)
    except DatabaseError:
        logger.exception("Failed to load broadcast users for weekly question")
        return

    # Pick rune of the week (same for everyone)
    weekly_rune = rune_of_week(RUNES, week)
    question = question_for_rune(weekly_rune["key"], week)

    # Filter: premium + preferred day matches today
    eligible = []
    for user in users:
        try:
            expires_at = user.get("premium_expires_at") or ""
            if not (expires_at and expires_at > today_str):
                continue
            preferred_day = user.get("weekly_question_day", 6)
            if preferred_day == today_weekday:
                eligible.append(user)
        except Exception:
            pass

    logger.info("Weekly question: week=%d rune=%s, sending to %d users", week, weekly_rune["name"], len(eligible))
    sent = blocked = errors = 0

    for user in eligible:
        user_id = user["user_id"]
        if not await _claim_delivery("weekly-question", today_str, user_id):
            continue
        palette = user.get("palette") or "light"
        image_path = _bot.get_rune_image_path(weekly_rune, palette)
        text = (
            f"{reading_title('🪬', 'Руна недели')}\n\n"
            f"{rune_block(weekly_rune['name'])}\n\n"
            f"❔ <b>Вопрос для размышления</b>\n{question}\n\n"
            f"<i>Можно просто подержать вопрос в голове. "
            f"Или сразу спросить руны — кнопка ниже.</i>"
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔮 Спросить руны об этом", callback_data=f"weekly_rasklad:{week}")
        ]])
        try:
            if image_path:
                await _bot.send_cached_photo(
                    context.bot.send_photo,
                    image_path,
                    chat_id=user_id,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=kb,
                )
            else:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=kb,
                )
            sent += 1
            await _finish_delivery("weekly-question", today_str, user_id, True)
        except Forbidden:
            try:
                await asyncio.to_thread(set_broadcast_enabled, user_id, False)
            except DatabaseError:
                pass
            blocked += 1
            await _finish_delivery("weekly-question", today_str, user_id, True)
        except TelegramError:
            logger.exception("Failed to send weekly question to user_id=%s", user_id)
            errors += 1
            await _finish_delivery("weekly-question", today_str, user_id, False)

    logger.info("Weekly question done: sent=%d blocked=%d errors=%d", sent, blocked, errors)


async def send_premium_expiry_warnings(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback: warn users whose premium expires in 1-3 days."""
    today = date.today()
    warn_dates = [(today + timedelta(days=d)).isoformat() for d in (1, 2, 3)]
    try:
        rows = await asyncio.to_thread(get_expiring_premium_users, warn_dates)
    except Exception:
        logger.exception("Failed to query expiring premium users")
        return

    for row in rows:
        user_id, name, expires_at = row["user_id"], row["preferred_name"], row["premium_expires_at"]
        delivery_date = today.isoformat()
        if not await _claim_delivery("premium-expiry", delivery_date, user_id):
            continue
        name = name or "друг"
        try:
            exp_date = date.fromisoformat(expires_at)
            days_left = (exp_date - today).days
            day_word = "день" if days_left == 1 else "дня"
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    f"💠 <b>{name}, твой премиум заканчивается через {days_left} {day_word}</b>\n\n"
                    "Чтобы продлить подписку — нажми 💠 Премиум в меню или напиши /premium."
                ),
                parse_mode="HTML",
                reply_markup=_bot.main_keyboard_for(user_id),
            )
            await _finish_delivery("premium-expiry", delivery_date, user_id, True)
        except Exception:
            logger.exception("Failed to send expiry warning to user_id=%s", user_id)
            await _finish_delivery("premium-expiry", delivery_date, user_id, False)


async def send_monthly_rune(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback: send rune of the month on the 1st day of each month."""
    today = date.today()
    if today.day != 1:
        return  # Job runs daily, only acts on 1st
    try:
        users = await asyncio.to_thread(get_broadcast_users)
    except DatabaseError:
        logger.exception("Failed to load users for monthly rune")
        return

    import random as _random
    from runes_data import RUNES as _RUNES
    # Pick one rune for everyone — same rune of the month
    monthly_rune = _random.choice(_RUNES)
    month_names = [
        "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
        "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
    ]
    month_label = month_names[today.month]

    logger.info("Monthly rune broadcast: %s, %d users", monthly_rune["name"], len(users))
    sent = errors = 0

    for user in users:
        user_id = user["user_id"]
        delivery_date = f"{today.year:04d}-{today.month:02d}"
        if not await _claim_delivery("monthly-rune", delivery_date, user_id):
            continue
        palette = user["palette"] or "light"
        palette_icon = {"light": "🌕", "dark": "🌑", "premium": "💠"}.get(palette, "🌕")
        try:
            image_path = _bot.get_rune_image_path(monthly_rune, palette)
            from rune_text_repository import get_daily_text
            rune_text = get_daily_text(monthly_rune["key"], palette, "up")
            text = (
                f"{reading_title(palette_icon, f'Руна месяца · {month_label}')}\n\n"
                f"{rune_block(monthly_rune['name'])}\n\n"
                f"🔎 <b>Основной смысл</b>\n{rune_text}\n\n"
                "🧭 <b>Ориентир на месяц</b>\n"
                "Держи смысл этой руны в уме при важных решениях."
            )
            from telegram import ReplyKeyboardRemove
            if image_path:
                await _bot.send_cached_photo(
                    context.bot.send_photo, image_path, chat_id=user_id,
                    caption=reading_title(palette_icon, f"Руна месяца · {month_label}")
                    + "\n\n" + rune_block(monthly_rune["name"]),
                    parse_mode="HTML",
                )
                await context.bot.send_message(
                    chat_id=user_id, text=text, parse_mode="HTML",
                    reply_markup=ReplyKeyboardRemove(),
                )
            else:
                await context.bot.send_message(
                    chat_id=user_id, text=text, parse_mode="HTML",
                    reply_markup=ReplyKeyboardRemove(),
                )
            sent += 1
            await _finish_delivery("monthly-rune", delivery_date, user_id, True)
        except Exception:
            logger.exception("Failed to send monthly rune to user_id=%s", user_id)
            errors += 1
            await _finish_delivery("monthly-rune", delivery_date, user_id, False)

    logger.info("Monthly rune done: sent=%d errors=%d", sent, errors)


async def subscribe_command(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enable daily broadcast for the user."""
    if not update.effective_user or not update.effective_message:
        return
    try:
        await asyncio.to_thread(set_broadcast_enabled, update.effective_user.id, True)
    except DatabaseError:
        await update.effective_message.reply_text(
            "Не получилось включить рассылку. Попробуй позже.",
            reply_markup=_bot.main_keyboard_for(update.effective_user.id),
        )
        return
    await update.effective_message.reply_text(
        "🌞 Рассылка включена. Каждое утро в 9:00 буду присылать тебе руну дня.",
        reply_markup=_bot.main_keyboard_for(update.effective_user.id),
    )


async def unsubscribe_command(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disable daily broadcast for the user."""
    if not update.effective_user or not update.effective_message:
        return
    try:
        await asyncio.to_thread(set_broadcast_enabled, update.effective_user.id, False)
    except DatabaseError:
        await update.effective_message.reply_text(
            "Не получилось отключить рассылку. Попробуй позже.",
            reply_markup=_bot.main_keyboard_for(update.effective_user.id),
        )
        return
    await update.effective_message.reply_text(
        "Рассылка отключена. Чтобы снова получать руну дня — напиши /subscribe.",
        reply_markup=_bot.main_keyboard_for(update.effective_user.id),
    )
