"""Premium subscription logic for the rune bot."""
import os
from datetime import date, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import bot as _bot
from database import get_connection, ensure_schema

PREMIUM_PRICE_STARS = 99
PREMIUM_PRICE_RUB = 299
PREMIUM_MONTHLY_READINGS = 3

PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "")

PREMIUM_BENEFITS = (
    "💠 <b>Премиум-подписка</b>\n\n"
    "💠 <b>Премиум-колода</b> — уникальные карты с более глубоким слоем трактовок. "
    "Недоступны в бесплатной версии.\n\n"
    "🕯 <b>3 личных расклада в месяц бесплатно</b> — живой ответ человека на твой вопрос. "
    "Без дополнительной оплаты.\n\n"
    "🪬 <b>Еженедельный вопрос для рефлексии</b> — каждое воскресенье приходит один вопрос. "
    "Не про руны — про тебя. Чтобы остановиться и посмотреть честно.\n\n"
    f"<b>Стоимость: {PREMIUM_PRICE_STARS} Stars / {PREMIUM_PRICE_RUB} ₽ в месяц</b>"
)


def get_premium_info_text(name: str) -> str:
    return f"✦ {name}, вот что даёт премиум:\n\n" + PREMIUM_BENEFITS.split("\n\n", 1)[1]


def get_premium_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⭐ Оплатить {PREMIUM_PRICE_STARS} Stars", callback_data="premium:buy:stars")],
        [InlineKeyboardButton(f"💳 Оплатить {PREMIUM_PRICE_RUB} ₽", callback_data="premium:buy:card")],
        [InlineKeyboardButton("✖ Закрыть", callback_data="premium:close")],
    ])


def is_premium_active(db_path: str, user_id: int) -> bool:
    from database import get_premium_status
    status = get_premium_status(db_path, user_id)
    expires_at = status.get("expires_at")
    if not expires_at:
        return False
    try:
        return date.fromisoformat(expires_at) > date.today()
    except ValueError:
        return False


def activate_premium(db_path: str, user_id: int) -> None:
    from database import set_premium_expires, reset_premium_readings, set_broadcast_enabled
    expires_at = (date.today() + timedelta(days=31)).isoformat()
    set_premium_expires(db_path, user_id, expires_at)
    reset_premium_readings(db_path, user_id)
    # Auto-set palette to premium
    try:
        from database import set_user_palette
        set_user_palette(db_path, user_id, "premium")
    except Exception:
        _bot.logger.exception("Failed to set premium palette on activation")
    # Auto-enable daily broadcast
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
