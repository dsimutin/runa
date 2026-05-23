"""Weekly intention setting — Premium feature."""
import sqlite3
from datetime import date

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

import bot as _bot
from database import get_connection, ensure_schema, DatabaseError, get_user_profile
from premium_subscription import is_premium_active

STATE_WAITING_INTENTION = "waiting_intention"


def get_intention(db_path: str, user_id: int) -> str | None:
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            row = conn.execute(
                "SELECT intention_text FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            return row[0] if row and row[0] else None
    except sqlite3.Error:
        return None


def set_intention(db_path: str, user_id: int, text: str) -> None:
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            conn.execute(
                "UPDATE users SET intention_text = ?, intention_set_at = ? WHERE user_id = ?",
                (text.strip(), date.today().isoformat(), user_id),
            )
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def clear_intention(db_path: str, user_id: int) -> None:
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            conn.execute(
                "UPDATE users SET intention_text = NULL, intention_set_at = NULL WHERE user_id = ?",
                (user_id,),
            )
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


async def intention_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show current intention or prompt to set one. Premium only."""
    if not update.effective_user or not update.effective_message:
        return
    user_id = update.effective_user.id

    if not is_premium_active(_bot.DB_PATH, user_id):
        await update.effective_message.reply_text(
            "🔒 Руна-намерение доступна только в <b>Премиум</b>.\n\n"
            "Нажми 💠 Премиум в меню, чтобы узнать подробности.",
            parse_mode=ParseMode.HTML,
        )
        return

    current = get_intention(_bot.DB_PATH, user_id)
    if current:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Изменить намерение", callback_data="intention:change")],
            [InlineKeyboardButton("🗑 Убрать намерение", callback_data="intention:clear")],
        ])
        await update.effective_message.reply_text(
            f"🌿 <b>Твоё намерение на эту неделю:</b>\n\n<i>{current}</i>\n\n"
            "Оно будет приходить вместе с утренней руной дня.",
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )
    else:
        context.user_data["state"] = STATE_WAITING_INTENTION
        await update.effective_message.reply_text(
            "🌿 <b>Руна-намерение</b>\n\n"
            "Напиши одно намерение на эту неделю — одну фразу, которую хочешь держать в голове.\n\n"
            "<i>Например: «Замедлиться и слушать себя» или «Закончить то, что начала»</i>",
            parse_mode=ParseMode.HTML,
        )


async def handle_intention_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Save intention text."""
    text = (update.effective_message.text or "").strip()
    if not text or len(text) > 200:
        await update.effective_message.reply_text(
            "Намерение должно быть не длиннее 200 символов. Попробуй ещё раз."
        )
        return
    user_id = update.effective_user.id
    set_intention(_bot.DB_PATH, user_id, text)
    context.user_data.pop("state", None)
    await update.effective_message.reply_text(
        f"🌿 Намерение сохранено:\n\n<i>{text}</i>\n\n"
        "Оно будет появляться в утренней рассылке.",
        parse_mode=ParseMode.HTML,
    )


async def intention_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if query.data == "intention:clear":
        clear_intention(_bot.DB_PATH, user_id)
        await query.message.reply_text("Намерение удалено.")
    elif query.data == "intention:change":
        context.user_data["state"] = STATE_WAITING_INTENTION
        await query.message.reply_text(
            "Напиши новое намерение — одну фразу:",
            parse_mode=ParseMode.HTML,
        )
