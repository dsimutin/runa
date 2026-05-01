import random
import sqlite3
from typing import Any, Dict, List, Tuple


class DatabaseError(Exception):
    """Custom database error for user-facing handling."""


def get_connection(db_path: str) -> sqlite3.Connection:
    """Create SQLite connection with safer defaults."""
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create and migrate all required tables. Safe to run repeatedly."""
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
            preferred_name TEXT NOT NULL DEFAULT 'друг'
        )
        """
    )

    columns = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    migrations = {
        "preferred_name": "ALTER TABLE users ADD COLUMN preferred_name TEXT NOT NULL DEFAULT 'друг'",
        "palette": "ALTER TABLE users ADD COLUMN palette TEXT",
        "psychotype": "ALTER TABLE users ADD COLUMN psychotype TEXT",
        "onboarding_step": "ALTER TABLE users ADD COLUMN onboarding_step INTEGER NOT NULL DEFAULT 0",
        "onboarding_score_light": "ALTER TABLE users ADD COLUMN onboarding_score_light INTEGER NOT NULL DEFAULT 0",
        "onboarding_score_dark": "ALTER TABLE users ADD COLUMN onboarding_score_dark INTEGER NOT NULL DEFAULT 0",
    }
    for column, sql in migrations.items():
        if column not in columns:
            conn.execute(sql)


def init_db(db_path: str) -> None:
    """Create required tables if they do not exist."""
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def ensure_user(db_path: str, user_id: int, preferred_name: str) -> None:
    """Create user row if it does not exist. Existing preferences are preserved."""
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO users (user_id, preferred_name)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET preferred_name = excluded.preferred_name
                """,
                (user_id, preferred_name or "друг"),
            )
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def get_user_profile(db_path: str, user_id: int) -> Dict[str, Any] | None:
    """Return user profile with palette/onboarding data."""
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            row = conn.execute(
                """
                SELECT preferred_name, palette, psychotype, onboarding_step,
                       onboarding_score_light, onboarding_score_dark
                FROM users
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
            if not row:
                return None
            return {
                "preferred_name": row[0],
                "palette": row[1],
                "psychotype": row[2],
                "onboarding_step": row[3] or 0,
                "onboarding_score_light": row[4] or 0,
                "onboarding_score_dark": row[5] or 0,
            }
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def start_onboarding(db_path: str, user_id: int) -> None:
    """Reset onboarding progress without removing daily runes."""
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            conn.execute(
                """
                UPDATE users
                SET palette = NULL,
                    psychotype = NULL,
                    onboarding_step = 1,
                    onboarding_score_light = 0,
                    onboarding_score_dark = 0
                WHERE user_id = ?
                """,
                (user_id,),
            )
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def save_onboarding_answer(db_path: str, user_id: int, answer: str, total_questions: int) -> Dict[str, Any]:
    """Save one onboarding answer. answer must be 'light' or 'dark'."""
    if answer not in {"light", "dark"}:
        raise DatabaseError("Invalid onboarding answer")

    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            row = conn.execute(
                """
                SELECT onboarding_step, onboarding_score_light, onboarding_score_dark
                FROM users
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
            if not row:
                conn.execute(
                    """
                    INSERT INTO users (user_id, preferred_name, onboarding_step)
                    VALUES (?, 'друг', 1)
                    """,
                    (user_id,),
                )
                row = (1, 0, 0)

            step = row[0] or 1
            light_score = row[1] or 0
            dark_score = row[2] or 0

            if answer == "light":
                light_score += 1
            else:
                dark_score += 1

            if step >= total_questions:
                palette = "light" if light_score >= dark_score else "dark"
                psychotype = "intuitive_integrator" if palette == "light" else "will_strategist"
                conn.execute(
                    """
                    UPDATE users
                    SET palette = ?,
                        psychotype = ?,
                        onboarding_step = 0,
                        onboarding_score_light = ?,
                        onboarding_score_dark = ?
                    WHERE user_id = ?
                    """,
                    (palette, psychotype, light_score, dark_score, user_id),
                )
                return {
                    "completed": True,
                    "palette": palette,
                    "psychotype": psychotype,
                    "light_score": light_score,
                    "dark_score": dark_score,
                }

            conn.execute(
                """
                UPDATE users
                SET onboarding_step = ?,
                    onboarding_score_light = ?,
                    onboarding_score_dark = ?
                WHERE user_id = ?
                """,
                (step + 1, light_score, dark_score, user_id),
            )
            return {
                "completed": False,
                "next_step": step + 1,
                "light_score": light_score,
                "dark_score": dark_score,
            }
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def get_or_create_daily_runes(db_path: str, user_id: int, day: str, runes: List[Dict[str, Any]]) -> Tuple[str, str]:
    """Return user's daily runes. Create two different runes on first request of the day."""
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
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
            ensure_schema(conn)
            row = conn.execute("SELECT preferred_name FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return row[0] if row else None
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def set_preferred_name(db_path: str, user_id: int, preferred_name: str) -> None:
    """Save or update preferred name."""
    ensure_user(db_path, user_id, preferred_name)
