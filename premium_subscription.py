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
    "💠 <b>Премиум-колода</b> — уникальные карты с архетипом, искажением и ключевым действием. "
    "Недоступны в бесплатной версии.\n\n"
    "🗓 <b>Расклад на год</b> — 12 рун на каждый месяц. "
    "Стабильный прогноз на весь год, персональный для тебя.\n\n"
    "🔮 <b>Рунический профиль</b> — руна жизни и руна текущего года по дате рождения. "
    "Постоянная личная карта.\n\n"
    "🕯 <b>3 личных расклада в месяц бесплатно</b> — живой ответ человека на твой вопрос.\n\n"
    "🪬 <b>Еженедельный вопрос для рефлексии</b> — каждое воскресенье приходит один вопрос про тебя.\n\n"
    "📜 <b>История раскладов</b> — последние 10 вопросов и ответов сохраняются.\n\n"
    f"<b>Стоимость: {PREMIUM_PRICE_STARS} Stars / {PREMIUM_PRICE_RUB} ₽ в месяц</b>"
)


def get_premium_info_text(name: str) -> str:
    return f"✦ {name}, вот что даёт премиум:\n\n" + PREMIUM_BENEFITS.split("\n\n", 1)[1]


def get_premium_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✨ Попробовать 7 дней бесплатно", callback_data="premium:trial")],
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


def activate_premium(db_path: str, user_id: int, is_trial: bool = False) -> None:
    from database import set_premium_expires, reset_premium_readings, set_premium_trial
    days = 7 if is_trial else 31
    expires_at = (date.today() + timedelta(days=days)).isoformat()
    set_premium_expires(db_path, user_id, expires_at)
    reset_premium_readings(db_path, user_id)
    set_premium_trial(db_path, user_id, is_trial)
    # Also set palette to premium
    try:
        from database import set_user_palette
        set_user_palette(db_path, user_id, "premium")
    except Exception:
        _bot.logger.exception("Failed to set premium palette on activation")


def get_free_readings_left(db_path: str, user_id: int) -> int:
    from database import get_premium_status
    status = get_premium_status(db_path, user_id)
    used = status.get("readings_used", 0) or 0
    return max(0, PREMIUM_MONTHLY_READINGS - used)


def use_free_reading(db_path: str, user_id: int) -> None:
    from database import increment_premium_readings
    increment_premium_readings(db_path, user_id)
