"""Расклад на год — 12 рун на 12 месяцев."""
import hashlib
from datetime import date
from typing import Any, Dict, List
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

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
    from telegram.constants import ParseMode
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
    lines.append("\n<i>Нажми на название руны, чтобы увидеть её трактовку.</i>")

    message_text = "\n".join(lines)
    image_path = _bot.get_rune_image_path(current_rune, palette)

    # Create inline buttons for each rune
    buttons = []
    for i, rune_name in enumerate(rune_names):
        month_num = i + 1
        buttons.append([InlineKeyboardButton(f"{MONTH_NAMES[i]} — {rune_name}", callback_data=f"year_rune:{user_id}:{year}:{month_num}")])

    keyboard = InlineKeyboardMarkup(buttons)
    message = update.effective_message
    user_id = update.effective_user.id

    if message and _bot.is_private(update):
        # Send text with buttons first
        await message.reply_text(message_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        # Send image separately if available
        if image_path:
            with open(image_path, "rb") as image_file:
                await message.reply_photo(photo=image_file)
    else:
        # For group chats, send to private chat
        await context.bot.send_message(chat_id=user_id, text=message_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        if image_path:
            with open(image_path, "rb") as image_file:
                await context.bot.send_photo(chat_id=user_id, photo=image_file)


async def send_rune_year_details(update, context, user_id: int, year: int, month_num: int) -> None:
    """Show detailed interpretation for a rune with month navigation."""
    import bot as _bot
    from telegram.constants import ParseMode
    from rune_text_repository import get_daily_text
    from runes_data import RUNES, get_rune_by_name

    query = update.callback_query
    if query:
        await query.answer()

    palette = _bot.get_user_palette(update)
    rune_names = get_year_runes(user_id, year, RUNES)
    rune_name = rune_names[month_num - 1]
    rune = get_rune_by_name(rune_name)

    today = date.today()
    is_past = (year < today.year) or (year == today.year and month_num < today.month)
    is_current = (year == today.year and month_num == today.month)

    marker = "✅" if is_past else ("▶️" if is_current else "·")
    text = get_daily_text(rune["key"], palette, "up")

    lines = [f"{marker} <b>{MONTH_NAMES[month_num - 1]} {year}</b> — {rune_name}\n"]
    lines.append(text)

    message_text = "\n".join(lines)
    image_path = _bot.get_rune_image_path(rune, palette)

    # Navigation buttons
    buttons = []
    nav_row = []
    if month_num > 1:
        nav_row.append(InlineKeyboardButton("← Предыдущий месяц", callback_data=f"year_rune:{user_id}:{year}:{month_num - 1}"))
    if month_num < 12:
        nav_row.append(InlineKeyboardButton("Следующий месяц →", callback_data=f"year_rune:{user_id}:{year}:{month_num + 1}"))
    if nav_row:
        buttons.append(nav_row)
    buttons.append([InlineKeyboardButton("← Вернуться к раскладу", callback_data=f"year_rasklad_back:{user_id}:{year}")])

    keyboard = InlineKeyboardMarkup(buttons)

    if query and query.message:
        await query.edit_message_text(message_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    else:
        await context.bot.send_message(chat_id=user_id, text=message_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


async def send_year_rasklad_from_callback(update, context, user_id: int, year: int) -> None:
    """Send year rasklad again from callback (for back button)."""
    import bot as _bot
    from telegram.constants import ParseMode
    from rune_text_repository import get_daily_text
    from runes_data import RUNES, get_rune_by_name

    query = update.callback_query
    if query:
        await query.answer()

    palette = _bot.get_user_palette(update)
    today = date.today()
    current_month = today.month if year == today.year else 1

    rune_names = get_year_runes(user_id, year, RUNES)

    lines = [f"🗓 <b>Расклад на {year} год</b>\n"]
    for i, rune_name in enumerate(rune_names):
        month_num = i + 1
        if month_num < current_month:
            marker = "✅"
        elif month_num == current_month and year == today.year:
            marker = "▶️"
        else:
            marker = "·"
        lines.append(f"{marker} <b>{MONTH_NAMES[i]}</b> — {rune_name}")

    if year == today.year:
        current_rune = get_rune_by_name(rune_names[current_month - 1])
        current_text = get_daily_text(current_rune["key"], palette, "up")
        lines.append(f"\n▶️ <b>Сейчас — {MONTH_NAMES[current_month - 1]}:</b>\n{current_text}")
    lines.append("\n<i>Руны года стабильны — каждый месяц задаёт свою энергию.</i>")
    lines.append("\n<i>Нажми на название руны, чтобы увидеть её трактовку.</i>")

    message_text = "\n".join(lines)
    image_path = None
    if year == today.year:
        current_rune = get_rune_by_name(rune_names[current_month - 1])
        image_path = _bot.get_rune_image_path(current_rune, palette)

    # Create inline buttons for each rune
    buttons = []
    for i, rune_name in enumerate(rune_names):
        month_num = i + 1
        buttons.append([InlineKeyboardButton(f"{MONTH_NAMES[i]} — {rune_name}", callback_data=f"year_rune:{user_id}:{year}:{month_num}")])

    keyboard = InlineKeyboardMarkup(buttons)
    if query and query.message:
        # Edit existing message with buttons
        await query.edit_message_text(message_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    else:
        # Send new message with buttons
        await context.bot.send_message(chat_id=user_id, text=message_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        if image_path:
            with open(image_path, "rb") as image_file:
                await context.bot.send_photo(chat_id=user_id, photo=image_file)
