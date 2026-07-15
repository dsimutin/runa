"""Premium subscription logic for the rune bot."""
import os
from datetime import date, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import bot as _bot

PREMIUM_PRICE_STARS = 99
PREMIUM_PRICE_RUB = 299
PREMIUM_MONTHLY_READINGS = 3
TRIAL_DAYS = 7

PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "")

PREMIUM_BENEFITS = (
    "💠 <b>Премиум-подписка</b>\n\n"
    "💠 <b>Премиум-колода</b> — уникальные карты с более глубоким слоем трактовок и особой энергетикой.\n\n"
    "🗓 <b>Расклад на год</b> — 12 рун на 12 месяцев. Видишь весь год целиком и фокус каждого периода.\n\n"
    "👥 <b>Расклад на взаимоотношения</b> — два типа: личные (любовь, дружба, семья) и деловые (работа, партнёрство).\n\n"
    "🕯 <b>3 личных расклада в месяц</b> — живой ответ человека на твой вопрос за 5–10 минут (19:00–22:00 Мск).\n\n"
    "🪬 <b>Еженедельный вопрос для рефлексии</b> — руна недели и вопрос в выбранный тобой день.\n\n"
    f"<b>Стоимость: {PREMIUM_PRICE_STARS} Stars / {PREMIUM_PRICE_RUB} ₽ в месяц</b>\n\n"
    f"🎁 <b>Попробовать бесплатно</b> — {TRIAL_DAYS} дней: премиум-колода, руна дня и расклад на год"
)


def get_premium_info_text(name: str) -> str:
    return f"✦ {name}, вот что даёт премиум:\n\n" + PREMIUM_BENEFITS.split("\n\n", 1)[1]


def get_premium_keyboard(user_id: int = 0) -> InlineKeyboardMarkup:
    """Build premium keyboard. Shows trial button if user hasn't used trial yet."""
    buttons = []
    if user_id and not is_trial_used(user_id):
        buttons.append([InlineKeyboardButton(
            f"🎁 Попробовать {TRIAL_DAYS} дней бесплатно",
            callback_data="premium:trial"
        )])
    buttons.append([InlineKeyboardButton(f"⭐ Оплатить {PREMIUM_PRICE_STARS} Stars", callback_data="premium:buy:stars")])
    buttons.append([InlineKeyboardButton(f"💳 Оплатить {PREMIUM_PRICE_RUB} ₽", callback_data="premium:buy:card")])
    buttons.append([InlineKeyboardButton("✖ Закрыть", callback_data="premium:close")])
    return InlineKeyboardMarkup(buttons)


def is_premium_active(user_id: int) -> bool:
    """Return True if paid premium OR trial is currently active."""
    from database import get_premium_status
    status = get_premium_status(user_id)

    expires_at = status.get("expires_at")
    if expires_at:
        try:
            if date.fromisoformat(expires_at) > date.today():
                return True
        except ValueError:
            pass

    trial_expires_at = status.get("trial_expires_at")
    if trial_expires_at:
        try:
            if date.fromisoformat(trial_expires_at) > date.today():
                return True
        except ValueError:
            pass

    return False


def is_trial_active(user_id: int) -> bool:
    """Return True if the user is on a trial (not paid premium)."""
    from database import get_premium_status
    status = get_premium_status(user_id)

    expires_at = status.get("expires_at")
    if expires_at:
        try:
            if date.fromisoformat(expires_at) > date.today():
                return False
        except ValueError:
            pass

    trial_expires_at = status.get("trial_expires_at")
    if trial_expires_at:
        try:
            return date.fromisoformat(trial_expires_at) > date.today()
        except ValueError:
            pass

    return False


def is_trial_used(user_id: int) -> bool:
    """Return True if the user has already used or is using a trial."""
    from database import get_premium_status
    status = get_premium_status(user_id)
    return bool(status.get("trial_expires_at"))


def activate_trial(user_id: int) -> str:
    """Activate 7-day trial. Returns expiry date string."""
    from database import set_trial_expires, set_user_palette
    expires_at = (date.today() + timedelta(days=TRIAL_DAYS)).isoformat()
    set_trial_expires(user_id, expires_at)
    try:
        set_user_palette(user_id, "premium")
    except Exception:
        _bot.logger.exception("Failed to set premium palette on trial activation")
    return expires_at


def activate_premium(user_id: int) -> None:
    from database import set_premium_expires, reset_premium_readings, set_user_palette
    expires_at = (date.today() + timedelta(days=31)).isoformat()
    set_premium_expires(user_id, expires_at)
    reset_premium_readings(user_id)
    try:
        set_user_palette(user_id, "premium")
    except Exception:
        _bot.logger.exception("Failed to set premium palette on activation")


def get_free_readings_left(user_id: int) -> int:
    """Trial users get 0 free readings. Paid premium users get 3/month."""
    if is_trial_active(user_id):
        return 0
    from database import get_premium_status
    status = get_premium_status(user_id)
    used = status.get("readings_used", 0) or 0
    return max(0, PREMIUM_MONTHLY_READINGS - used)


def use_free_reading(user_id: int) -> None:
    from database import increment_premium_readings
    increment_premium_readings(user_id)
