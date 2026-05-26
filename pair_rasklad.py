"""Pair reading module — /pair <name> command."""

from datetime import date

import bot as _bot
from database import get_pair_rasklad_runes
from rune_text_repository import get_rasklad_text
from runes_data import RUNES, get_rune_by_name


async def _build_pair_text(update, context, partner_name: str) -> None:
    """Core logic shared by pair_rasklad_command and pair_name_received."""
    if not await _bot.ensure_profile_ready(update, context):
        return

    user_id = update.effective_user.id
    palette = _bot.get_user_palette(update)
    today = date.today().isoformat()

    rune1_name, rune2_name, rune3_name = get_pair_rasklad_runes(
        user_id, partner_name, today, RUNES
    )

    rune1 = get_rune_by_name(rune1_name)
    rune2 = get_rune_by_name(rune2_name)
    rune3 = get_rune_by_name(rune3_name)

    result1 = get_rasklad_text(rune1["key"], palette, "up", "past")
    result2 = get_rasklad_text(rune2["key"], palette, "up", "present")
    result3 = get_rasklad_text(rune3["key"], palette, "up", "future")

    message_text = (
        f"✌️ <b>Ты и {partner_name}</b>\n"
        f"\n"
        f"👤 <b>Ты</b> — {rune1_name}\n"
        f"{result1['text']}\n"
        f"\n"
        f"👥 <b>{partner_name}</b> — {rune2_name}\n"
        f"{result2['text']}\n"
        f"\n"
        f"🔗 <b>Что между вами</b> — {rune3_name}\n"
        f"{result3['text']}"
    )

    image_path = _bot.get_rune_image_path(rune3, palette)
    await _bot.send_private_or_group(update, context, message_text, image_path=image_path, reading_mode=True)


async def pair_rasklad_command(update, context):
    """Handler for /pair <name> — reading for two people."""
    if not context.args:
        await update.effective_message.reply_text(
            "✌️ Напиши имя человека: /pair Анна",
            reply_markup=_bot.MAIN_KEYBOARD,
        )
        return
    partner_name = " ".join(context.args)
    await _build_pair_text(update, context, partner_name)


async def pair_name_received(update, context, partner_name: str):
    """Called when the user provides a partner name after /pair without arguments."""
    await _build_pair_text(update, context, partner_name)
