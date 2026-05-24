"""History command — rune of day (last 7), streak, and spread history for premium."""

import bot as _bot
from database import get_rune_history, get_streak, get_spread_history

SPREAD_TYPE_LABELS = {
    "yes_no": "❓ Да/Нет",
    "three_card": "🔮 Расклад",
}


async def history_command(update, context):
    if not update.effective_user or not update.effective_message:
        return

    user_id = update.effective_user.id
    history = get_rune_history(_bot.DB_PATH, user_id, 7)
    streak = get_streak(_bot.DB_PATH, user_id)

    if not history:
        await update.effective_message.reply_text(
            "Ты ещё не открывал руну дня. Нажми 🌞 Руна дня — начнём.",
            reply_markup=_bot.MAIN_KEYBOARD,
        )
        return

    lines = []
    for entry in history:
        parts = entry["date"].split("-")
        display_date = f"{parts[2]}.{parts[1]}"
        arrow = "↑" if entry["orientation"] == "up" else "↓"
        lines.append(f"{display_date} — {entry['rune_name']} {arrow}")

    streak_line = (
        f"🔥 {streak} {'день' if streak == 1 else 'дня' if 2 <= streak <= 4 else 'дней'} подряд"
        if streak > 0
        else "Серия пока не набрана — открывай руну каждый день."
    )

    text = (
        f"📅 <b>Твои руны за 7 дней</b>\n"
        f"\n"
        f"{chr(10).join(lines)}\n"
        f"\n"
        f"{streak_line}"
    )

    # Premium: append last 10 spread readings
    from premium_subscription import is_premium_active
    if is_premium_active(_bot.DB_PATH, user_id):
        spreads = get_spread_history(_bot.DB_PATH, user_id, limit=10)
        if spreads:
            spread_lines = []
            for s in spreads:
                label = SPREAD_TYPE_LABELS.get(s["spread_type"], "📖")
                date_short = s["created_at"][:10] if s["created_at"] else "—"
                parts2 = date_short.split("-")
                date_fmt = f"{parts2[2]}.{parts2[1]}" if len(parts2) == 3 else date_short
                q = (s["question"] or "")[:45]
                if len(s["question"] or "") > 45:
                    q += "..."
                runes = s["rune_names"]
                spread_lines.append(f"{date_fmt} {label} {runes}" + (f"\n<i>{q}</i>" if q else ""))
            text += f"\n\n💠 <b>История раскладов</b>\n\n" + "\n\n".join(spread_lines)
    else:
        text += "\n\n<i>История вопросов и раскладов — функция премиума 💠</i>"

    await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=_bot.MAIN_KEYBOARD)
