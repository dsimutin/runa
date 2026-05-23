"""Celtic Cross — 10-card spread (Premium only)."""
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

import bot as _bot
from database import DatabaseError, get_user_profile
from premium_subscription import is_premium_active
from rune_text_repository import draw_distinct_runes_with_orientations, get_rasklad_text
from runes_data import RUNES

POSITIONS = [
    ("present",  "🔮 Настоящее",        "Суть ситуации"),
    ("cross",    "✝️ Пересечение",       "Что мешает или помогает"),
    ("past",     "⬅️ Прошлое",           "Основа, откуда это пришло"),
    ("future",   "➡️ Ближайшее будущее", "Что приближается"),
    ("above",    "⬆️ Сознательное",      "Твоя цель, к чему стремишься"),
    ("below",    "⬇️ Подсознательное",   "Скрытый мотив, корень"),
    ("approach", "🪞 Твой подход",       "Как ты действуешь сейчас"),
    ("external", "🌍 Внешнее",           "Окружение, люди вокруг"),
    ("hopes",    "💭 Надежды и страхи",  "Что ожидаешь от исхода"),
    ("outcome",  "🌟 Итог",              "Куда ведёт этот путь"),
]

# Map our position keys to rune_text_repository positions
_POS_MAP = {
    "present": "present",
    "cross": "present",
    "past": "past",
    "future": "future",
    "above": "future",
    "below": "past",
    "approach": "present",
    "external": "present",
    "hopes": "future",
    "outcome": "future",
}


async def celtic_cross_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send Celtic Cross 10-card spread. Premium only."""
    if not update.effective_user or not update.effective_message:
        return
    user_id = update.effective_user.id

    if not is_premium_active(_bot.DB_PATH, user_id):
        await update.effective_message.reply_text(
            "🔒 Кельтский крест доступен только в <b>Премиум</b>.\n\n"
            "Нажми 💠 Премиум в меню, чтобы узнать подробности.",
            parse_mode=ParseMode.HTML,
        )
        return

    profile = get_user_profile(_bot.DB_PATH, user_id) or {}
    palette = profile.get("palette") or "premium"
    name = profile.get("preferred_name") or "друг"

    draws = draw_distinct_runes_with_orientations(RUNES, count=10)

    lines = [f"✝️ <b>{name}, Кельтский крест</b>\n<i>Полный расклад из 10 рун</i>\n"]
    for i, (pos_key, pos_label, pos_desc) in enumerate(POSITIONS):
        rune, orientation = draws[i]
        rune_pos = _POS_MAP.get(pos_key, "present")
        rune_text_data = get_rasklad_text(rune["key"], palette, orientation, rune_pos)
        direction = "↑" if orientation == "up" else "↓"
        rune_text = rune_text_data.get("text", "")
        lines.append(
            f"{pos_label} — <i>{pos_desc}</i>\n"
            f"<b>{rune['name']}</b> {direction} — {rune_text}\n"
        )

    text = "\n".join(lines)

    # Split into 2 messages if too long
    if len(text) > 4000:
        mid = len(POSITIONS) // 2
        text1_lines = lines[:mid + 1]
        text2_lines = [lines[0]] + lines[mid + 1:]
        await update.effective_message.reply_text("\n".join(text1_lines), parse_mode=ParseMode.HTML)
        await update.effective_message.reply_text("\n".join(text2_lines), parse_mode=ParseMode.HTML)
    else:
        await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)
