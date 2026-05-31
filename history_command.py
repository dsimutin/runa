"""History command — show last 7 days of daily runes + streak."""

import bot as _bot
from database import get_rune_history, get_streak


async def history_command(update, context):
    """Show the user's rune history for the last 7 days and current streak."""
    if not update.effective_user or not update.effective_message:
        return

    user_id = update.effective_user.id
    history = get_rune_history(user_id, 7)
    streak = get_streak(user_id)

    if not history:
        await update.effective_message.reply_text(
            "Ты ещё не открывал руну дня. Нажми 🌞 Руна дня — начнём.",
            reply_markup=_bot.MAIN_KEYBOARD,
        )
        return

    lines = []
    for entry in history:
        raw_date = entry["date"]          # "2026-05-20"
        parts = raw_date.split("-")
        display_date = f"{parts[2]}.{parts[1]}"  # "20.05"
        arrow = "↑" if entry["orientation"] == "up" else "↓"
        lines.append(f"{display_date} — {entry['rune_name']} {arrow}")

    history_block = "\n".join(lines)
    streak_line = f"🔥 {streak} {'день' if streak == 1 else 'дня' if 2 <= streak <= 4 else 'дней'} подряд" if streak > 0 else "Серия пока не набрана — открывай руну каждый день."

    text = (
        f"📅 <b>Твои руны за 7 дней</b>\n"
        f"\n"
        f"{history_block}\n"
        f"\n"
        f"{streak_line}"
    )

    await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=_bot.MAIN_KEYBOARD)
