import random
import sqlite3
from typing import Any, Dict, List, Tuple


class DatabaseError(Exception):
    """Custom database error for user-facing handling."""


VALID_PALETTES = {"light", "dark", "premium"}
DAILY_ORIENTATIONS = {"up", "rev"}


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
        "onboarding_score_premium": "ALTER TABLE users ADD COLUMN onboarding_score_premium INTEGER NOT NULL DEFAULT 0",
        "broadcast_enabled": "ALTER TABLE users ADD COLUMN broadcast_enabled INTEGER NOT NULL DEFAULT 1",
        "premium_expires_at": "ALTER TABLE users ADD COLUMN premium_expires_at TEXT",
        "premium_readings_used": "ALTER TABLE users ADD COLUMN premium_readings_used INTEGER NOT NULL DEFAULT 0",
        "weekly_question_day": "ALTER TABLE users ADD COLUMN weekly_question_day INTEGER NOT NULL DEFAULT 6",
        "birth_date": "ALTER TABLE users ADD COLUMN birth_date TEXT",
        "premium_is_trial": "ALTER TABLE users ADD COLUMN premium_is_trial INTEGER NOT NULL DEFAULT 0",
    }
    for column, sql in migrations.items():
        if column not in columns:
            conn.execute(sql)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_spreads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            spread_type TEXT NOT NULL,
            question TEXT,
            rune_names TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_spreads_user ON user_spreads(user_id, created_at DESC)"
    )


def init_db(db_path: str) -> None:
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def ensure_user(db_path: str, user_id: int, preferred_name: str) -> None:
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
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            row = conn.execute(
                """
                SELECT preferred_name, palette, psychotype, onboarding_step,
                       onboarding_score_light, onboarding_score_dark, onboarding_score_premium
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
                "onboarding_score_premium": row[6] or 0,
            }
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def start_onboarding(db_path: str, user_id: int) -> None:
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
                    onboarding_score_dark = 0,
                    onboarding_score_premium = 0
                WHERE user_id = ?
                """,
                (user_id,),
            )
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def _psychotype_for_palette(palette: str) -> str:
    if palette == "dark":
        return "will_strategist"
    if palette == "premium":
        return "premium_seeker"
    return "intuitive_integrator"


def _winning_palette(light_score: int, dark_score: int, premium_score: int) -> str:
    scores = {"light": light_score, "dark": dark_score, "premium": premium_score}
    top = max(scores.values())
    winners = [palette for palette, score in scores.items() if score == top]
    if "premium" in winners:
        return "premium"
    if "light" in winners:
        return "light"
    return "dark"


def save_onboarding_answer(db_path: str, user_id: int, answer: str, total_questions: int) -> Dict[str, Any]:
    # Onboarding only assigns light/dark; premium is via subscription only
    if answer not in {"light", "dark"}:
        raise DatabaseError("Invalid onboarding answer")

    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            row = conn.execute(
                """
                SELECT onboarding_step, onboarding_score_light, onboarding_score_dark, onboarding_score_premium
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
                row = (1, 0, 0, 0)

            step = row[0] or 1
            light_score = row[1] or 0
            dark_score = row[2] or 0
            premium_score = row[3] or 0

            if answer == "light":
                light_score += 1
            elif answer == "dark":
                dark_score += 1
            else:
                premium_score += 1

            if step >= total_questions:
                palette = _winning_palette(light_score, dark_score, premium_score)
                psychotype = _psychotype_for_palette(palette)
                conn.execute(
                    """
                    UPDATE users
                    SET palette = ?,
                        psychotype = ?,
                        onboarding_step = 0,
                        onboarding_score_light = ?,
                        onboarding_score_dark = ?,
                        onboarding_score_premium = ?
                    WHERE user_id = ?
                    """,
                    (palette, psychotype, light_score, dark_score, premium_score, user_id),
                )
                return {
                    "completed": True,
                    "palette": palette,
                    "psychotype": psychotype,
                    "light_score": light_score,
                    "dark_score": dark_score,
                    "premium_score": premium_score,
                }

            conn.execute(
                """
                UPDATE users
                SET onboarding_step = ?,
                    onboarding_score_light = ?,
                    onboarding_score_dark = ?,
                    onboarding_score_premium = ?
                WHERE user_id = ?
                """,
                (step + 1, light_score, dark_score, premium_score, user_id),
            )
            return {
                "completed": False,
                "next_step": step + 1,
                "light_score": light_score,
                "dark_score": dark_score,
                "premium_score": premium_score,
            }
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def set_user_palette(db_path: str, user_id: int, palette: str) -> None:
    if palette not in VALID_PALETTES:
        raise DatabaseError("Invalid palette")
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            conn.execute(
                """
                UPDATE users
                SET palette = ?, psychotype = ?
                WHERE user_id = ?
                """,
                (palette, _psychotype_for_palette(palette), user_id),
            )
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def _random_orientation_for_rune(rune: Dict[str, Any]) -> str:
    if rune.get("key") in {"wyrd", "blank"} or rune.get("name") == "Пустая руна":
        return "up"
    return random.choice(["up", "rev"])


def get_or_create_daily_card(db_path: str, user_id: int, day: str, runes: List[Dict[str, Any]]) -> Tuple[str, str]:
    """Return one daily rune and its orientation.

    The legacy daily_runes.aux_rune column is reused as orientation:
    up = прямое, rev = перевёрнутое. For the empty rune only up is allowed.
    """
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

            if row and row[1] in DAILY_ORIENTATIONS:
                orientation = "up" if row[0] == "Пустая руна" else row[1]
                if orientation != row[1]:
                    conn.execute(
                        """
                        UPDATE daily_runes
                        SET aux_rune = ?
                        WHERE user_id = ? AND date = ?
                        """,
                        (orientation, user_id, day),
                    )
                return row[0], orientation

            if row:
                rune_name = row[0]
                rune = next((item for item in runes if item["name"] == rune_name), random.choice(runes))
                orientation = _random_orientation_for_rune(rune)
                conn.execute(
                    """
                    UPDATE daily_runes
                    SET aux_rune = ?
                    WHERE user_id = ? AND date = ?
                    """,
                    (orientation, user_id, day),
                )
                return rune["name"], orientation

            rune = random.choice(runes)
            orientation = _random_orientation_for_rune(rune)
            conn.execute(
                """
                INSERT INTO daily_runes (user_id, date, main_rune, aux_rune)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, day, rune["name"], orientation),
            )
            return rune["name"], orientation
    except (sqlite3.Error, ValueError) as exc:
        raise DatabaseError(str(exc)) from exc


def get_or_create_daily_runes(db_path: str, user_id: int, day: str, runes: List[Dict[str, Any]]) -> Tuple[str, str]:
    """Backward compatible wrapper for older imports."""
    return get_or_create_daily_card(db_path, user_id, day, runes)


def get_preferred_name(db_path: str, user_id: int) -> str | None:
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            row = conn.execute("SELECT preferred_name FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return row[0] if row else None
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def set_preferred_name(db_path: str, user_id: int, preferred_name: str) -> None:
    ensure_user(db_path, user_id, preferred_name)


def get_broadcast_users(db_path: str) -> List[Dict[str, Any]]:
    """Return all users with a chosen palette who have broadcast enabled."""
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT user_id, preferred_name, palette
                FROM users
                WHERE palette IS NOT NULL
                  AND broadcast_enabled = 1
                """
            ).fetchall()
            return [{"user_id": row[0], "preferred_name": row[1], "palette": row[2]} for row in rows]
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def set_broadcast_enabled(db_path: str, user_id: int, enabled: bool) -> None:
    """Enable or disable daily broadcast for a user."""
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            conn.execute(
                "UPDATE users SET broadcast_enabled = ? WHERE user_id = ?",
                (1 if enabled else 0, user_id),
            )
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def set_weekly_question_day(db_path: str, user_id: int, day: int) -> None:
    """Set preferred weekday for weekly reflection question (0=Mon … 6=Sun)."""
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            conn.execute(
                "UPDATE users SET weekly_question_day = ? WHERE user_id = ?",
                (day, user_id),
            )
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def get_rune_history(db_path: str, user_id: int, days: int = 7) -> List[Dict[str, Any]]:
    """Return rune history for the last N days, newest first.

    Each entry: {"date": "2026-05-20", "rune_name": "Феху", "orientation": "up"}
    """
    from datetime import date, timedelta

    cutoff = (date.today() - timedelta(days=days - 1)).isoformat()
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT date, main_rune, aux_rune
                FROM daily_runes
                WHERE user_id = ? AND date >= ?
                ORDER BY date DESC
                """,
                (user_id, cutoff),
            ).fetchall()
            return [
                {
                    "date": row[0],
                    "rune_name": row[1],
                    "orientation": row[2] if row[2] in DAILY_ORIENTATIONS else "up",
                }
                for row in rows
            ]
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def get_streak(db_path: str, user_id: int) -> int:
    """Count how many consecutive days the user has opened the rune of the day.

    Counts backward from today; if today has an entry, streak starts at 1.
    """
    from datetime import date, timedelta

    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT date FROM daily_runes
                WHERE user_id = ?
                ORDER BY date DESC
                """,
                (user_id,),
            ).fetchall()

        dates = {row[0] for row in rows}
        streak = 0
        current = date.today()
        while current.isoformat() in dates:
            streak += 1
            current -= timedelta(days=1)
        return streak
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def get_premium_status(db_path: str, user_id: int) -> dict:
    """Return {"expires_at": str|None, "readings_used": int}."""
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            row = conn.execute(
                "SELECT premium_expires_at, premium_readings_used FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if not row:
                return {"expires_at": None, "readings_used": 0}
            return {"expires_at": row[0], "readings_used": row[1] or 0}
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def set_premium_expires(db_path: str, user_id: int, expires_at: str) -> None:
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            conn.execute(
                "UPDATE users SET premium_expires_at = ? WHERE user_id = ?",
                (expires_at, user_id),
            )
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def increment_premium_readings(db_path: str, user_id: int) -> None:
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            conn.execute(
                "UPDATE users SET premium_readings_used = COALESCE(premium_readings_used, 0) + 1 WHERE user_id = ?",
                (user_id,),
            )
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def reset_premium_readings(db_path: str, user_id: int) -> None:
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            conn.execute(
                "UPDATE users SET premium_readings_used = 0 WHERE user_id = ?",
                (user_id,),
            )
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def get_pair_rasklad_runes(
    db_path: str,
    user_id: int,
    partner_name: str,
    day: str,
    runes: List[Dict[str, Any]],
) -> Tuple[str, str, str]:
    """Return a deterministic triple of rune names for a pair reading.

    Returns (rune1_name, rune2_name, rune3_name):
      rune1 — for the user, rune2 — for the partner, rune3 — the bond between them.
    The selection is reproducible for the same (user_id, partner_name, day) triple.
    """
    import hashlib

    seed = hashlib.md5(f"{user_id}:{partner_name.lower()}:{day}".encode()).hexdigest()

    # Use the 32-char hex digest as a base-16 number to derive three distinct indices
    seed_int = int(seed, 16)
    total = len(runes)

    indices: List[int] = []
    used: set = set()
    i = 0
    while len(indices) < 3:
        idx = (seed_int >> (i * 8)) % total
        if idx not in used:
            indices.append(idx)
            used.add(idx)
        i += 1
        if i > 256:
            # Fallback: just pick first available
            for j in range(total):
                if j not in used:
                    indices.append(j)
                    used.add(j)
                    if len(indices) == 3:
                        break
            break

    return runes[indices[0]]["name"], runes[indices[1]]["name"], runes[indices[2]]["name"]


def get_birth_date(db_path: str, user_id: int) -> str | None:
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            row = conn.execute("SELECT birth_date FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return row[0] if row else None
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def set_birth_date(db_path: str, user_id: int, birth_date: str) -> None:
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            conn.execute("UPDATE users SET birth_date = ? WHERE user_id = ?", (birth_date, user_id))
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def save_spread(db_path: str, user_id: int, spread_type: str, question: str | None, rune_names: str) -> None:
    from datetime import datetime
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            conn.execute(
                "INSERT INTO user_spreads (user_id, spread_type, question, rune_names, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, spread_type, question, rune_names, datetime.utcnow().strftime("%Y-%m-%d %H:%M")),
            )
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def get_spread_history(db_path: str, user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            rows = conn.execute(
                "SELECT spread_type, question, rune_names, created_at FROM user_spreads WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
            return [
                {"spread_type": r[0], "question": r[1], "rune_names": r[2], "created_at": r[3]}
                for r in rows
            ]
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def set_premium_trial(db_path: str, user_id: int, is_trial: bool) -> None:
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            conn.execute("UPDATE users SET premium_is_trial = ? WHERE user_id = ?", (1 if is_trial else 0, user_id))
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc


def is_premium_trial(db_path: str, user_id: int) -> bool:
    try:
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            row = conn.execute("SELECT premium_is_trial FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return bool(row and row[0])
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc
