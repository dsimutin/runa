"""Premium subscription logic for the rune bot."""
import os
from datetime import date, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import bot as _bot
from database import get_connection, ensure_schema

PREMIUM_PRICE_STARS = 99
PREMIUM_PRICE_RUB = 299
PREMIUM_ANNUAL_RUB = 2490
PREMIUM_ANNUAL_STARS = 830
PREMIUM_MONTHLY_READINGS = 3
TRIAL_DAYS = 3

PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "")

PREMIUM_BENEFITS = (
    "💠 <b>Премиум-подписка</b>\n\n"
    "💠 <b>Премиум-колода</b> — уникальные карты с более глубоким слоем трактовок.\n\n"
    "🕯 <b>3 личных расклада в месяц бесплатно</b> — живой ответ человека на твой вопрос.\n\n"
    "🪬 <b>Еженедельный вопрос для рефлексии</b> — вопрос про тебя, не про руны.\n\n"
    "📅 <b>Расклад на месяц</b> — 4 руны на 4 недели вперёд.\n\n"
    "✝️ <b>Кельтский крест</b> — глубокий расклад из 10 рун.\n\n"
    "🌿 <b>Руна-намерение</b> — фраза недели в утренней рассылке.\n\n"
    "🌟 <b>Личная руна жизни</b> — твоя руна по дате рождения.\n\n"
    f"<b>Стоимость: {PREMIUM_PRICE_STARS} Stars / {PREMIUM_PRICE_RUB} ₽ в месяц</b>\n"
    f"<b>Или {PREMIUM_ANNUAL_RUB} ₽ / {PREMIUM_ANNUAL_STARS} Stars за год</b>"
)


def get_premium_info_text(name: str) -> str:
    return f"✦ {name}, вот что даёт премиум:\n\n" + PREMIUM_BENEFITS.split("\n\n", 1)[1]


def get_premium_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⭐ {PREMIUM_PRICE_STARS} Stars / месяц", callback_data="premium:buy:stars")],
        [InlineKeyboardButton(f"💳 {PREMIUM_PRICE_RUB} ₽ / месяц", callback_data="premium:buy:card")],
        [InlineKeyboardButton(f"⭐ {PREMIUM_ANNUAL_STARS} Stars / год", callback_data="premium:buy:stars_annual")],
        [InlineKeyboardButton(f"💳 {PREMIUM_ANNUAL_RUB} ₽ / год", callback_data="premium:buy:card_annual")],
        [InlineKeyboardButton("🎁 Попробовать 3 дня бесплатно", callback_data="premium:trial")],
        [InlineKeyboardButton("✖ Закрыть", callback_data="premium:close")],
    ])


def is_premium_active(db_path: str, user_id: int) -> bool:
    from database import get_premium_status
    status = get_premium_status(db_path, user_id)
    expires_at = status.get("expires_at")
    if not expires_at:
        # Check trial
        return _is_trial_active(db_path, user_id)
    try:
        return date.fromisoformat(expires_at) > date.today()
    except ValueError:
        return False


def _is_trial_active(db_path: str, user_id: int) -> bool:
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            row = conn.execute(
                "SELECT trial_expires_at FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            if row and row[0]:
                return date.fromisoformat(row[0]) > date.today()
    except Exception:
        pass
    return False


def has_used_trial(db_path: str, user_id: int) -> bool:
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            row = conn.execute(
                "SELECT trial_used FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            return bool(row and row[0])
    except Exception:
        return False


def activate_trial(db_path: str, user_id: int) -> None:
    """Activate 3-day free trial (once per user)."""
    from database import set_user_palette, set_broadcast_enabled
    trial_expires = (date.today() + timedelta(days=TRIAL_DAYS)).isoformat()
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            conn.execute(
                "UPDATE users SET trial_used = 1, trial_expires_at = ? WHERE user_id = ?",
                (trial_expires, user_id),
            )
    except Exception:
        _bot.logger.exception("Failed to activate trial")
        return
    try:
        set_user_palette(db_path, user_id, "premium")
    except Exception:
        pass
    try:
        set_broadcast_enabled(db_path, user_id, True)
    except Exception:
        pass


def activate_premium(db_path: str, user_id: int, days: int = 31) -> None:
    from database import set_premium_expires, reset_premium_readings, set_broadcast_enabled
    expires_at = (date.today() + timedelta(days=days)).isoformat()
    set_premium_expires(db_path, user_id, expires_at)
    reset_premium_readings(db_path, user_id)
    try:
        from database import set_user_palette
        set_user_palette(db_path, user_id, "premium")
    except Exception:
        _bot.logger.exception("Failed to set premium palette on activation")
    try:
        set_broadcast_enabled(db_path, user_id, True)
    except Exception:
        _bot.logger.exception("Failed to enable broadcast on premium activation")


def get_free_readings_left(db_path: str, user_id: int) -> int:
    from database import get_premium_status
    status = get_premium_status(db_path, user_id)
    used = status.get("readings_used", 0) or 0
    return max(0, PREMIUM_MONTHLY_READINGS - used)


def use_free_reading(db_path: str, user_id: int) -> None:
    from database import increment_premium_readings
    increment_premium_readings(db_path, user_id)
