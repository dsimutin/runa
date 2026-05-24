"""Расклад на год — 12 рун на 12 месяцев."""
import hashlib
from datetime import date
from typing import Any, Dict, List

MONTH_NAMES = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]


def get_year_runes(user_id: int, year: int, runes: List[Dict[str, Any]]) -> List[str]:
    """12 уникальных рун на 12 месяцев — стабильны для конкретного user_id + year."""
    seed = int(hashlib.md5(f"{user_id}:{year}:year".encode()).hexdigest(), 16)
    available = list(runes)
    result = []
    state = seed
    for _ in range(12):
        state = (state * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
        idx = state % len(available)
        result.append(available[idx]["name"])
        available.pop(idx)
    return result


async def send_year_rasklad(update, context) -> None:
    import bot as _bot
    from rune_text_repository import get_daily_text
    from runes_data import RUNES, get_rune_by_name

    if not await _bot.ensure_profile_ready(update, context):
        return

    user_id = update.effective_user.id
    palette = _bot.get_user_palette(update)
    today = date.today()
    year = today.year
    current_month = today.month

    rune_names = get_year_runes(user_id, year, RUNES)

    lines = [f"🗓 <b>Расклад на {year} год</b>\n"]
    for i, rune_name in enumerate(rune_names):
        month_num = i + 1
        if month_num < current_month:
            marker = "✅"
        elif month_num == current_month:
            marker = "▶️"
        else:
            marker = "·"
        lines.append(f"{marker} <b>{MONTH_NAMES[i]}</b> — {rune_name}")

    current_rune = get_rune_by_name(rune_names[current_month - 1])
    current_text = get_daily_text(current_rune["key"], palette, "up")
    lines.append(f"\n▶️ <b>Сейчас — {MONTH_NAMES[current_month - 1]}:</b>\n{current_text}")
    lines.append("\n<i>Руны года стабильны — каждый месяц задаёт свою энергию.</i>")

    message_text = "\n".join(lines)
    image_path = _bot.get_rune_image_path(current_rune, palette)
    await _bot.send_private_or_group(update, context, message_text, image_path=image_path)
