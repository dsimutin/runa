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
    get_connection,
    set_broadcast_enabled,
)
from lunar_calendar import moon_phase_today
from rune_text_repository import get_daily_text
from runes_data import RUNES, get_rune_by_name
from weekly_questions import question_for_rune, rune_of_week

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

        # Append intention for premium users
        intention_line = ""
        try:
            from premium_subscription import is_premium_active
            if is_premium_active(_bot.DB_PATH, user_id):
                with get_connection(_bot.DB_PATH) as _conn:
                    _row = _conn.execute(
                        "SELECT intention_text FROM users WHERE user_id = ?", (user_id,)
                    ).fetchone()
                    if _row and _row[0]:
                        intention_line = f"\n\n🌿 <i>Намерение: {_row[0]}</i>"
        except Exception:
            pass

        text = (
            f"{palette_icon} <b>{name}, руна дня</b>\n\n"
            f"<b>{rune['name']}</b> · {orientation_label}\n\n"
            f"{day_text}\n\n"
            f"{moon['emoji']} {moon['phase_name']} — {moon['description']}"
            f"{intention_line}"
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
    """Job callback: send weekly rune + reflection question to premium subscribers.

    Runs daily; each user has a preferred weekday (weekly_question_day, 0=Mon…6=Sun).
    Only sends to users whose preferred day matches today.
    """
    from database import get_premium_status, get_connection
    from datetime import date as _date
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from runes_data import RUNES

    today = _date.today()
    today_str = today.isoformat()
    today_weekday = today.weekday()  # 0=Mon … 6=Sun
    week = today.isocalendar()[1]

    try:
        users = get_broadcast_users(_bot.DB_PATH)
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
            status = get_premium_status(_bot.DB_PATH, user["user_id"])
            expires_at = status.get("expires_at") or ""
            if not (expires_at and expires_at > today_str):
                continue
            # Check preferred day (default 6 = Sunday)
            with get_connection(_bot.DB_PATH) as conn:
                row = conn.execute(
                    "SELECT weekly_question_day FROM users WHERE user_id = ?",
                    (user["user_id"],)
                ).fetchone()
            preferred_day = row[0] if row and row[0] is not None else 6
            if preferred_day == today_weekday:
                eligible.append(user)
        except Exception:
            pass

    logger.info("Weekly question: week=%d rune=%s, sending to %d users", week, weekly_rune["name"], len(eligible))
    sent = blocked = errors = 0

    for user in eligible:
        user_id = user["user_id"]
        palette = user.get("palette") or "light"
        palette_icon = {"light": "🌕", "dark": "🌑", "premium": "💠"}.get(palette, "🌕")

        image_path = _bot.get_rune_image_path(weekly_rune, palette)
        text = (
            f"🪬 <b>Руна недели — {weekly_rune['name']}</b>\n\n"
            f"<b>Вопрос для рефлексии:</b>\n{question}\n\n"
            f"<i>Можно просто подержать вопрос в голове. "
            f"Или сразу спросить руны — кнопка ниже.</i>"
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔮 Спросить руны об этом", callback_data=f"weekly_rasklad:{week}")
        ]])
        try:
            if image_path:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=open(image_path, "rb"),
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
        except Forbidden:
            try:
                set_broadcast_enabled(_bot.DB_PATH, user_id, False)
            except DatabaseError:
                pass
            blocked += 1
        except TelegramError:
            logger.exception("Failed to send weekly question to user_id=%s", user_id)
            errors += 1

    logger.info("Weekly question done: sent=%d blocked=%d errors=%d", sent, blocked, errors)


async def send_premium_expiry_warnings(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback: warn users whose premium expires in 1-3 days."""
    today = date.today()
    warn_dates = [(today + timedelta(days=d)).isoformat() for d in (1, 2, 3)]
    try:
        with get_connection(_bot.DB_PATH) as conn:
            rows = conn.execute(
                "SELECT user_id, preferred_name, premium_expires_at FROM users "
                "WHERE premium_expires_at IN (?, ?, ?)",
                warn_dates,
            ).fetchall()
    except Exception:
        logger.exception("Failed to query expiring premium users")
        return

    for row in rows:
        user_id, name, expires_at = row
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
                reply_markup=_bot.MAIN_KEYBOARD,
            )
        except Exception:
            logger.exception("Failed to send expiry warning to user_id=%s", user_id)


async def send_monthly_rune(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback: send rune of the month on the 1st day of each month."""
    today = date.today()
    if today.day != 1:
        return  # Job runs daily, only acts on 1st
    try:
        users = get_broadcast_users(_bot.DB_PATH)
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
        name = user["preferred_name"] or "друг"
        palette = user["palette"] or "light"
        palette_icon = {"light": "🌕", "dark": "🌑", "premium": "💠"}.get(palette, "🌕")
        try:
            image_path = _bot.get_rune_image_path(monthly_rune, palette)
            from rune_text_repository import get_daily_text
            rune_text = get_daily_text(monthly_rune["key"], palette, "up")
            text = (
                f"{palette_icon} <b>{name}, руна {month_label}а</b>\n\n"
                f"<b>{monthly_rune['name']}</b>\n\n"
                f"{rune_text}\n\n"
                f"<i>Эта руна задаёт тон месяца. Держи её в уме при важных решениях.</i>"
            )
            if image_path:
                await context.bot.send_photo(
                    chat_id=user_id, photo=open(image_path, "rb"),
                    caption=text, parse_mode="HTML", reply_markup=_bot.MAIN_KEYBOARD,
                )
            else:
                await context.bot.send_message(
                    chat_id=user_id, text=text, parse_mode="HTML",
                    reply_markup=_bot.MAIN_KEYBOARD,
                )
            sent += 1
        except Exception:
            logger.exception("Failed to send monthly rune to user_id=%s", user_id)
            errors += 1

    logger.info("Monthly rune done: sent=%d errors=%d", sent, errors)


async def send_streak_reminders(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback: remind users who haven't drawn a rune in 2 days."""
    from datetime import date as _date, timedelta as _timedelta
    yesterday = (_date.today() - _timedelta(days=1)).isoformat()
    day_before = (_date.today() - _timedelta(days=2)).isoformat()

    try:
        with get_connection(_bot.DB_PATH) as conn:
            # Users who drew a rune 2 days ago but NOT yesterday and NOT today
            rows = conn.execute(
                """
                SELECT DISTINCT u.user_id, u.preferred_name
                FROM users u
                JOIN daily_runes dr ON dr.user_id = u.user_id AND dr.date = ?
                WHERE u.broadcast_enabled = 1
                  AND u.palette IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM daily_runes dr2
                    WHERE dr2.user_id = u.user_id AND dr2.date >= ?
                  )
                """,
                (day_before, yesterday),
            ).fetchall()
    except Exception:
        logger.exception("Failed to query streak reminder users")
        return

    logger.info("Streak reminders: sending to %d users", len(rows))
    for user_id, name in rows:
        name = name or "друг"
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    f"🔥 <b>{name}, твой стрик под угрозой!</b>\n\n"
                    "Ты не вытягивала руну уже 2 дня. Загляни сегодня — займёт меньше минуты."
                ),
                parse_mode="HTML",
                reply_markup=_bot.MAIN_KEYBOARD,
            )
        except Exception:
            pass


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
