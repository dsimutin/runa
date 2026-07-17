"""Расклад на год — 12 рун на 12 месяцев."""
import asyncio
import hashlib
import re
from datetime import date
from typing import Any, Dict, List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

MONTH_NAMES = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]


def build_month_interpretation(rune_key: str, palette: str) -> str:
    """Return a month-scale reading, never a recycled card-of-the-day text."""
    from rune_decks_approved import get_deck_meaning

    meaning = get_deck_meaning(rune_key, palette, False)
    body = meaning["text"]
    body = re.sub(r"\bСейчас\b", "В этом месяце", body)
    body = re.sub(r"\bсейчас\b", "в этом месяце", body)
    body = re.sub(r"\bСегодня\b", "В течение месяца", body)
    body = re.sub(r"\bсегодня\b", "в течение месяца", body)
    advice = meaning["advice"].strip()
    return f"<b>Тема месяца</b>\n{body}\n\n<b>Ориентир месяца</b>\n{advice}"


def _generate_year_runes(user_id: int, year: int, runes: List[Dict[str, Any]]) -> List[str]:
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


def get_year_runes(user_id: int, year: int, runes: List[Dict[str, Any]]) -> List[str]:
    """Stable 12 runes for user+year — stored in DB so they never change."""
    from database import get_or_create_year_runes
    return get_or_create_year_runes(user_id, year, lambda: _generate_year_runes(user_id, year, runes))


def _build_year_keyboard(rune_names: List[str], user_id: int, year: int) -> InlineKeyboardMarkup:
    today = date.today()
    buttons = []
    for i, rune_name in enumerate(rune_names):
        month_num = i + 1
        if year < today.year or (year == today.year and month_num < today.month):
            marker = "✅"
        elif year == today.year and month_num == today.month:
            marker = "▶️"
        else:
            marker = "·"
        label = f"{marker} {MONTH_NAMES[i]} — {rune_name}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"year_rune:{user_id}:{year}:{month_num}")])
    return InlineKeyboardMarkup(buttons)


async def send_year_rasklad(update, context) -> None:
    import bot as _bot
    from runes_data import RUNES

    if not await _bot.ensure_profile_ready(update, context):
        return

    user_id = update.effective_user.id
    year = date.today().year
    rune_names = await asyncio.to_thread(get_year_runes, user_id, year, RUNES)

    text = f"🗓 <b>Расклад на {year} год</b>\n\nНажми на месяц — увидишь трактовку руны."
    keyboard = _build_year_keyboard(rune_names, user_id, year)

    message = update.effective_message
    if message and _bot.is_private(update):
        await message.reply_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    else:
        await context.bot.send_message(
            chat_id=user_id, text=text, reply_markup=keyboard, parse_mode=ParseMode.HTML
        )


async def send_rune_year_details(update, context, user_id: int, year: int, month_num: int) -> None:
    """Show interpretation for a specific month with navigation."""
    import bot as _bot
    from runes_data import RUNES, get_rune_by_name

    query = update.callback_query
    if query:
        await query.answer()

    palette = _bot.get_user_palette(update)
    rune_names = await asyncio.to_thread(get_year_runes, user_id, year, RUNES)
    rune_name = rune_names[month_num - 1]
    rune = get_rune_by_name(rune_name)

    today = date.today()
    is_past = (year < today.year) or (year == today.year and month_num < today.month)
    is_current = year == today.year and month_num == today.month
    marker = "✅" if is_past else ("▶️" if is_current else "·")

    interpretation = build_month_interpretation(rune["key"], palette)
    message_text = (
        f"{marker} <b>{MONTH_NAMES[month_num - 1]} {year}</b> — {rune_name}\n\n"
        f"{interpretation}"
    )

    nav_row = []
    if month_num > 1:
        nav_row.append(InlineKeyboardButton(
            "← Предыдущий", callback_data=f"year_rune:{user_id}:{year}:{month_num - 1}"
        ))
    if month_num < 12:
        nav_row.append(InlineKeyboardButton(
            "Следующий →", callback_data=f"year_rune:{user_id}:{year}:{month_num + 1}"
        ))
    buttons = []
    if nav_row:
        buttons.append(nav_row)
    buttons.append([InlineKeyboardButton(
        "← Весь год", callback_data=f"year_rasklad_back:{user_id}:{year}"
    )])
    keyboard = InlineKeyboardMarkup(buttons)

    if query and query.message:
        await query.edit_message_text(message_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    else:
        await context.bot.send_message(
            chat_id=user_id, text=message_text, reply_markup=keyboard, parse_mode=ParseMode.HTML
        )


async def send_year_rasklad_from_callback(update, context, user_id: int, year: int) -> None:
    """Return to full year view from month detail."""
    from runes_data import RUNES

    query = update.callback_query
    if query:
        await query.answer()

    rune_names = await asyncio.to_thread(get_year_runes, user_id, year, RUNES)
    text = f"🗓 <b>Расклад на {year} год</b>\n\nНажми на месяц — увидишь трактовку руны."
    keyboard = _build_year_keyboard(rune_names, user_id, year)

    if query and query.message:
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    else:
        await context.bot.send_message(
            chat_id=user_id, text=text, reply_markup=keyboard, parse_mode=ParseMode.HTML
        )
