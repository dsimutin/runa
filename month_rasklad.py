"""Monthly spread — 4 runes for 4 weeks (Premium only)."""
from datetime import date

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

import bot as _bot
from database import DatabaseError, get_user_profile
from premium_subscription import is_premium_active
from rune_text_repository import draw_distinct_runes_with_orientations, get_rasklad_text
from runes_data import RUNES

WEEK_LABELS = ["Первая неделя", "Вторая неделя", "Третья неделя", "Четвёртая неделя"]
WEEK_EMOJIS = ["🌱", "🌿", "🍃", "🌾"]


async def month_rasklad_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send monthly 4-week rune spread. Premium only."""
    if not update.effective_user or not update.effective_message:
        return
    user_id = update.effective_user.id

    if not is_premium_active(_bot.DB_PATH, user_id):
        await update.effective_message.reply_text(
            "🔒 Расклад на месяц доступен только в <b>Премиум</b>.\n\n"
            "Нажми 💠 Премиум в меню, чтобы узнать подробности.",
            parse_mode=ParseMode.HTML,
        )
        return

    profile = get_user_profile(_bot.DB_PATH, user_id) or {}
    palette = profile.get("palette") or "premium"
    name = profile.get("preferred_name") or "друг"

    today = date.today()
    month_names = [
        "", "январь", "февраль", "март", "апрель", "май", "июнь",
        "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
    ]
    month_label = month_names[today.month]

    draws = draw_distinct_runes_with_orientations(RUNES, count=4)

    lines = [f"💠 <b>{name}, расклад на {month_label}</b>\n"]
    for i, (rune, orientation) in enumerate(draws):
        rune_text_data = get_rasklad_text(rune["key"], palette, orientation, "present")
        direction = "↑" if orientation == "up" else "↓"
        week_text = rune_text_data.get("text", "")
        lines.append(
            f"{WEEK_EMOJIS[i]} <b>{WEEK_LABELS[i]}</b>\n"
            f"<b>{rune['name']}</b> {direction}\n"
            f"{week_text}\n"
        )

    lines.append("<i>Держи эти образы в уме. Они не предсказание — они ориентиры.</i>")
    text = "\n".join(lines)

    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)
