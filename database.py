import random
import sqlite3
from typing import List, Dict, Any, Tuple


class DatabaseError(Exception):
    """Custom database error for user-facing handling."""


def get_connection(db_path: str) -> sqlite3.Connection:
    """Create SQLite connection."""
    return sqlite3.connect(db_path)


def init_db(db_path: str) -> None:
    """Create required tables if they do not exist."""
    try:
        with get_connection(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_runes (
                    user_id INTEGER NOT NULL,
                    date TEXT NOT NULL,
                    main_rune TEXT NOT NULL,
                    aux_rune TEXT NOT NULL,
                    PRIMARY KEY (user_id, date)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    preferred_name TEXT NOT NULL
                )
                """
            )
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def get_or_create_daily_runes(
    db_path: str,
    user_id: int,
    day: str,
    runes: List[Dict[str, Any]],
) -> Tuple[str, str]:
    """Return user's daily runes. Create two different runes on first request of the day."""
    try:
        with get_connection(db_path) as conn:
            row = conn.execute(
                """
                SELECT main_rune, aux_rune
                FROM daily_runes
                WHERE user_id = ? AND date = ?
                """,
                (user_id, day),
            ).fetchone()

            if row:
                return row[0], row[1]

            main_rune, aux_rune = random.sample(runes, 2)

            conn.execute(
                """
                INSERT INTO daily_runes (user_id, date, main_rune, aux_rune)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, day, main_rune["name"], aux_rune["name"]),
            )

            return main_rune["name"], aux_rune["name"]
    except (sqlite3.Error, ValueError) as exc:
        raise DatabaseError(str(exc)) from exc


def get_preferred_name(db_path: str, user_id: int) -> str | None:
    """Get saved preferred name."""
    try:
        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT preferred_name FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            return row[0] if row else None
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def set_preferred_name(db_path: str, user_id: int, preferred_name: str) -> None:
    """Save or update preferred name."""
    try:
        with get_connection(db_path) as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, preferred_name)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET preferred_name = excluded.preferred_name
                """,
                (user_id, preferred_name),
            )
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc
