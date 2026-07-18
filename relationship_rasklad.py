"""Relationship reading module — for personal and professional relationships."""

import asyncio
from datetime import date
from html import escape

import bot as _bot
from database import get_pair_rasklad_runes
from rune_text_repository import get_relationship_trio_texts
from reading_format import reading_title, rune_block
from runes_data import RUNES, get_rune_by_name


async def send_relationship_type_choice(update, context, person_name: str) -> None:
    """Show choice between personal and professional relationship readings."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    context.user_data["relationship_person"] = person_name

    buttons = [
        [InlineKeyboardButton("👥 Личные отношения", callback_data="rel_type:personal")],
        [InlineKeyboardButton("💼 Деловые отношения", callback_data="rel_type:business")],
    ]
    keyboard = InlineKeyboardMarkup(buttons)

    await update.effective_message.reply_text(
        f"👥 Расклад для <b>{escape(person_name)}</b> — выбери тип:\n\n"
        "👤 <i>Личные</i> — любовь, дружба, семья\n"
        "💼 <i>Деловые</i> — работа, партнёрство, сотрудничество",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


async def _build_relationship_text(update, context, person_name: str, rel_type: str) -> None:
    """Core logic for relationship reading."""
    if not await _bot.ensure_profile_ready(update, context):
        return

    user_id = update.effective_user.id
    palette = _bot.get_user_palette(update)
    today = date.today().isoformat()

    # Use same rune drawing as pair rasklad but with type context
    key_suffix = f":{rel_type}"
    rune1_name, rune2_name, rune3_name = await asyncio.to_thread(
        get_pair_rasklad_runes, user_id, person_name + key_suffix, today, RUNES
    )

    rune1 = get_rune_by_name(rune1_name)
    rune2 = get_rune_by_name(rune2_name)
    rune3 = get_rune_by_name(rune3_name)

    texts = get_relationship_trio_texts(rune1["key"], rune2["key"], rune3["key"], palette)

    if rel_type == "personal":
        rel_label = reading_title("👥", "Личные отношения")
        your_label = "Твоя позиция"
        their_label = f"{escape(person_name)}: позиция в отношениях"
        between_label = "Динамика между вами"
    else:  # business
        rel_label = reading_title("💼", "Деловые отношения")
        your_label = "Твоя роль в сотрудничестве"
        their_label = f"{escape(person_name)}: роль в сотрудничестве"
        between_label = "Динамика сотрудничества"

    message_text = (
        f"{rel_label}\n"
        f"<b>Ты ↔ {escape(person_name)}</b>\n\n"
        f"1️⃣ <b>{your_label}</b>\n{rune_block(rune1_name)}\n\n"
        f"{texts['you']}\n"
        f"\n\n2️⃣ <b>{their_label}</b>\n{rune_block(rune2_name)}\n\n"
        f"{texts['partner']}\n"
        f"\n\n3️⃣ <b>{between_label}</b>\n{rune_block(rune3_name)}\n\n"
        f"{texts['between']}"
    )

    image_paths = [_bot.get_rune_image_path(rune, palette) for rune in (rune1, rune2, rune3)]
    image_path = None
    if all(image_paths):
        from rune_collage import build_spread_collage
        image_path = await asyncio.to_thread(
            build_spread_collage,
            image_paths,
            palette,
            ["ТЫ", person_name[:18], "МЕЖДУ ВАМИ"],
        )
    await _bot.send_private_or_group(
        update, context, message_text, image_path=image_path, reading_mode=True
    )


async def relationship_type_callback(update, context) -> None:
    """Handle relationship type selection."""
    query = update.callback_query
    if not query or not update.effective_user:
        return

    try:
        parts = query.data.split(":", 2)
        if parts[0] == "rel_type" and len(parts) >= 2:
            rel_type = parts[1]  # personal or business
            person_name = parts[2] if len(parts) == 3 else context.user_data.get("relationship_person", "")
            if not person_name:
                await query.answer("Напиши имя ещё раз.", show_alert=True)
                return

            await query.answer()
            await query.edit_message_text(f"⏳ Выбираю карты для {escape(person_name)}...", parse_mode="HTML")

            await _build_relationship_text(update, context, person_name, rel_type)
    except Exception:
        import bot as _bot
        _bot.logger.exception("Failed to handle relationship type callback")
        await query.answer("Что-то пошло не так.", show_alert=True)
