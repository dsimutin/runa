"""Referral system — users earn +7 days premium per invited friend."""
import sqlite3
from datetime import date, timedelta

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

import bot as _bot
from database import get_connection, ensure_schema, DatabaseError


def ensure_referral_schema(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            referred_id INTEGER PRIMARY KEY,
            referrer_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            rewarded INTEGER NOT NULL DEFAULT 0
        )
    """)


def store_referral(db_path: str, referrer_id: int, referred_id: int) -> bool:
    """Record referral. Returns True if it's new (not already stored)."""
    if referrer_id == referred_id:
        return False
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            ensure_referral_schema(conn)
            existing = conn.execute(
                "SELECT referrer_id FROM referrals WHERE referred_id = ?", (referred_id,)
            ).fetchone()
            if existing:
                return False
            conn.execute(
                "INSERT INTO referrals (referred_id, referrer_id, created_at) VALUES (?, ?, ?)",
                (referred_id, referrer_id, date.today().isoformat()),
            )
            return True
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def reward_referrer(db_path: str, referred_id: int) -> None:
    """Give referrer +7 days premium when referred user completes onboarding."""
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            ensure_referral_schema(conn)
            row = conn.execute(
                "SELECT referrer_id, rewarded FROM referrals WHERE referred_id = ?", (referred_id,)
            ).fetchone()
            if not row or row[1]:
                return
            referrer_id = row[0]
            # Extend premium by 7 days
            ref_row = conn.execute(
                "SELECT premium_expires_at FROM users WHERE user_id = ?", (referrer_id,)
            ).fetchone()
            if ref_row:
                expires = ref_row[0]
                try:
                    base = date.fromisoformat(expires) if expires else date.today()
                    if base < date.today():
                        base = date.today()
                except ValueError:
                    base = date.today()
                new_expires = (base + timedelta(days=7)).isoformat()
                conn.execute(
                    "UPDATE users SET premium_expires_at = ? WHERE user_id = ?",
                    (new_expires, referrer_id),
                )
            conn.execute(
                "UPDATE referrals SET rewarded = 1 WHERE referred_id = ?", (referred_id,)
            )
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def get_referral_stats(db_path: str, user_id: int) -> dict:
    """Return {'total': int, 'rewarded': int}."""
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            ensure_referral_schema(conn)
            row = conn.execute(
                "SELECT COUNT(*), SUM(rewarded) FROM referrals WHERE referrer_id = ?", (user_id,)
            ).fetchone()
            return {"total": row[0] or 0, "rewarded": row[1] or 0}
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def get_bot_username(context: ContextTypes.DEFAULT_TYPE) -> str:
    try:
        return context.bot.username or "runa_bot"
    except Exception:
        return "runa_bot"


async def referral_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show referral link and stats."""
    if not update.effective_user or not update.effective_message:
        return
    user_id = update.effective_user.id
    username = get_bot_username(context)
    link = f"https://t.me/{username}?start=ref_{user_id}"
    stats = get_referral_stats(_bot.DB_PATH, user_id)

    text = (
        "👥 <b>Пригласи друга</b>\n\n"
        f"Поделись своей ссылкой — за каждого друга, который пройдёт регистрацию, "
        f"ты получишь <b>+7 дней Премиум</b>.\n\n"
        f"🔗 Твоя ссылка:\n<code>{link}</code>\n\n"
        f"📊 Приглашено: <b>{stats['total']}</b> · Наград получено: <b>{stats['rewarded']}</b>"
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)
