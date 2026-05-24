import logging
import os
import random
from contextlib import contextmanager
from typing import Any, Dict, List, Tuple

import psycopg2
import psycopg2.extras
import psycopg2.pool

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

_schema_initialized = False
_pool: psycopg2.pool.ThreadedConnectionPool | None = None


class DatabaseError(Exception):
    """Custom database error for user-facing handling."""


VALID_PALETTES = {"light", "dark", "premium"}
DAILY_ORIENTATIONS = {"up", "rev"}


def _conn_url() -> str:
    if not DATABASE_URL:
        raise DatabaseError("DATABASE_URL env var is not set")
    url = DATABASE_URL
    if "sslmode=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}sslmode=require"
    return url


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None or _pool.closed:
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 5, dsn=_conn_url())
    return _pool


@contextmanager
def _db():
    """Borrow a connection from the pool, commit on success, rollback on error."""
    try:
        conn = _get_pool().getconn()
    except psycopg2.Error as exc:
        logger.error("DB connection failed: %s", exc)
        raise DatabaseError(f"Connection failed: {exc}") from exc
    try:
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            _get_pool().putconn(conn)
        except Exception:
            pass


def ensure_schema(conn) -> None:
    """Create all required tables. Runs once per process."""
    global _schema_initialized
    if _schema_initialized:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id                   BIGINT  PRIMARY KEY,
                preferred_name            TEXT    NOT NULL DEFAULT 'друг',
                palette                   TEXT,
                psychotype                TEXT,
                onboarding_step           INTEGER NOT NULL DEFAULT 0,
                onboarding_score_light    INTEGER NOT NULL DEFAULT 0,
                onboarding_score_dark     INTEGER NOT NULL DEFAULT 0,
                onboarding_score_premium  INTEGER NOT NULL DEFAULT 0,
                broadcast_enabled         INTEGER NOT NULL DEFAULT 1,
                premium_expires_at        TEXT,
                premium_readings_used     INTEGER NOT NULL DEFAULT 0,
                weekly_question_day       INTEGER NOT NULL DEFAULT 6,
                trial_expires_at          TEXT
            )
            """
        )
        # Migrate existing tables: add trial_expires_at if missing
        cur.execute(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_expires_at TEXT"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_runes (
                user_id   BIGINT NOT NULL,
                date      TEXT   NOT NULL,
                main_rune TEXT   NOT NULL,
                aux_rune  TEXT   NOT NULL,
                PRIMARY KEY (user_id, date)
            )
            """
        )
    _schema_initialized = True


def init_db() -> None:
    try:
        with _db() as conn:
            ensure_schema(conn)
        logger.info("Database schema ready (Supabase PostgreSQL)")
    except psycopg2.Error as exc:
        raise DatabaseError(str(exc)) from exc


def ensure_user(user_id: int, preferred_name: str) -> None:
    try:
        with _db() as conn:
            ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (user_id, preferred_name)
                    VALUES (%s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET preferred_name = EXCLUDED.preferred_name
                    """,
                    (user_id, preferred_name or "друг"),
                )
    except psycopg2.Error as exc:
        raise DatabaseError(str(exc)) from exc


def get_user_profile(user_id: int) -> Dict[str, Any] | None:
    try:
        with _db() as conn:
            ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT preferred_name, palette, psychotype, onboarding_step,
                           onboarding_score_light, onboarding_score_dark, onboarding_score_premium
                    FROM users
                    WHERE user_id = %s
                    """,
                    (user_id,),
                )
                row = cur.fetchone()
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
    except psycopg2.Error as exc:
        raise DatabaseError(str(exc)) from exc


def start_onboarding(user_id: int) -> None:
    try:
        with _db() as conn:
            ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE users
                    SET palette = NULL,
                        psychotype = NULL,
                        onboarding_step = 1,
                        onboarding_score_light = 0,
                        onboarding_score_dark = 0,
                        onboarding_score_premium = 0
                    WHERE user_id = %s
                    """,
                    (user_id,),
                )
    except psycopg2.Error as exc:
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


def save_onboarding_answer(user_id: int, answer: str, total_questions: int) -> Dict[str, Any]:
    if answer not in {"light", "dark"}:
        raise DatabaseError("Invalid onboarding answer")

    try:
        with _db() as conn:
            ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT onboarding_step, onboarding_score_light, onboarding_score_dark, onboarding_score_premium
                    FROM users
                    WHERE user_id = %s
                    """,
                    (user_id,),
                )
                row = cur.fetchone()
                if not row:
                    cur.execute(
                        "INSERT INTO users (user_id, preferred_name, onboarding_step) VALUES (%s, 'друг', 1)",
                        (user_id,),
                    )
                    row = (1, 0, 0, 0)

                step = row[0] or 1
                light_score = row[1] or 0
                dark_score = row[2] or 0
                premium_score = row[3] or 0

                if answer == "light":
                    light_score += 1
                else:
                    dark_score += 1

                if step >= total_questions:
                    palette = _winning_palette(light_score, dark_score, premium_score)
                    psychotype = _psychotype_for_palette(palette)
                    cur.execute(
                        """
                        UPDATE users
                        SET palette = %s,
                            psychotype = %s,
                            onboarding_step = 0,
                            onboarding_score_light = %s,
                            onboarding_score_dark = %s,
                            onboarding_score_premium = %s
                        WHERE user_id = %s
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

                cur.execute(
                    """
                    UPDATE users
                    SET onboarding_step = %s,
                        onboarding_score_light = %s,
                        onboarding_score_dark = %s,
                        onboarding_score_premium = %s
                    WHERE user_id = %s
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
    except psycopg2.Error as exc:
        raise DatabaseError(str(exc)) from exc


def set_user_palette(user_id: int, palette: str) -> None:
    if palette not in VALID_PALETTES:
        raise DatabaseError("Invalid palette")
    try:
        with _db() as conn:
            ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET palette = %s, psychotype = %s WHERE user_id = %s",
                    (palette, _psychotype_for_palette(palette), user_id),
                )
    except psycopg2.Error as exc:
        raise DatabaseError(str(exc)) from exc


def _random_orientation_for_rune(rune: Dict[str, Any]) -> str:
    if rune.get("key") in {"wyrd", "blank"} or rune.get("name") == "Пустая руна":
        return "up"
    return random.choice(["up", "rev"])


def get_or_create_daily_card(user_id: int, day: str, runes: List[Dict[str, Any]]) -> Tuple[str, str]:
    """Return one daily rune and its orientation (up/rev)."""
    try:
        with _db() as conn:
            ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT main_rune, aux_rune FROM daily_runes WHERE user_id = %s AND date = %s",
                    (user_id, day),
                )
                row = cur.fetchone()

                if row and row[1] in DAILY_ORIENTATIONS:
                    orientation = "up" if row[0] == "Пустая руна" else row[1]
                    if orientation != row[1]:
                        cur.execute(
                            "UPDATE daily_runes SET aux_rune = %s WHERE user_id = %s AND date = %s",
                            (orientation, user_id, day),
                        )
                    return row[0], orientation

                if row:
                    rune_name = row[0]
                    rune = next((r for r in runes if r["name"] == rune_name), random.choice(runes))
                    orientation = _random_orientation_for_rune(rune)
                    cur.execute(
                        "UPDATE daily_runes SET aux_rune = %s WHERE user_id = %s AND date = %s",
                        (orientation, user_id, day),
                    )
                    return rune["name"], orientation

                rune = random.choice(runes)
                orientation = _random_orientation_for_rune(rune)
                cur.execute(
                    "INSERT INTO daily_runes (user_id, date, main_rune, aux_rune) VALUES (%s, %s, %s, %s)",
                    (user_id, day, rune["name"], orientation),
                )
                return rune["name"], orientation
    except (psycopg2.Error, ValueError) as exc:
        raise DatabaseError(str(exc)) from exc


def get_or_create_daily_runes(user_id: int, day: str, runes: List[Dict[str, Any]]) -> Tuple[str, str]:
    """Backward compatible wrapper."""
    return get_or_create_daily_card(db_path, user_id, day, runes)


def get_preferred_name(user_id: int) -> str | None:
    try:
        with _db() as conn:
            ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT preferred_name FROM users WHERE user_id = %s", (user_id,))
                row = cur.fetchone()
                return row[0] if row else None
    except psycopg2.Error as exc:
        raise DatabaseError(str(exc)) from exc


def set_preferred_name(user_id: int, preferred_name: str) -> None:
    ensure_user(db_path, user_id, preferred_name)


def get_broadcast_users() -> List[Dict[str, Any]]:
    """Return all users with a chosen palette who have broadcast enabled."""
    try:
        with _db() as conn:
            ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT user_id, preferred_name, palette, weekly_question_day
                    FROM users
                    WHERE palette IS NOT NULL AND broadcast_enabled = 1
                    """
                )
                rows = cur.fetchall()
                return [
                    {
                        "user_id": row[0],
                        "preferred_name": row[1],
                        "palette": row[2],
                        "weekly_question_day": row[3] if row[3] is not None else 6,
                    }
                    for row in rows
                ]
    except psycopg2.Error as exc:
        raise DatabaseError(str(exc)) from exc


def set_broadcast_enabled(user_id: int, enabled: bool) -> None:
    try:
        with _db() as conn:
            ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET broadcast_enabled = %s WHERE user_id = %s",
                    (1 if enabled else 0, user_id),
                )
    except psycopg2.Error as exc:
        raise DatabaseError(str(exc)) from exc


def set_weekly_question_day(user_id: int, day: int) -> None:
    try:
        with _db() as conn:
            ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET weekly_question_day = %s WHERE user_id = %s",
                    (day, user_id),
                )
    except psycopg2.Error as exc:
        raise DatabaseError(str(exc)) from exc


def get_rune_history(user_id: int, days: int = 7) -> List[Dict[str, Any]]:
    from datetime import date, timedelta

    cutoff = (date.today() - timedelta(days=days - 1)).isoformat()
    try:
        with _db() as conn:
            ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT date, main_rune, aux_rune
                    FROM daily_runes
                    WHERE user_id = %s AND date >= %s
                    ORDER BY date DESC
                    """,
                    (user_id, cutoff),
                )
                rows = cur.fetchall()
                return [
                    {
                        "date": row[0],
                        "rune_name": row[1],
                        "orientation": row[2] if row[2] in DAILY_ORIENTATIONS else "up",
                    }
                    for row in rows
                ]
    except psycopg2.Error as exc:
        raise DatabaseError(str(exc)) from exc


def get_streak(user_id: int) -> int:
    from datetime import date, timedelta

    try:
        with _db() as conn:
            ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT date FROM daily_runes WHERE user_id = %s ORDER BY date DESC",
                    (user_id,),
                )
                rows = cur.fetchall()
        dates = {row[0] for row in rows}
        streak = 0
        current = date.today()
        while current.isoformat() in dates:
            streak += 1
            current -= timedelta(days=1)
        return streak
    except psycopg2.Error as exc:
        raise DatabaseError(str(exc)) from exc


def get_premium_status(user_id: int) -> dict:
    """Return {"expires_at": str|None, "readings_used": int, "trial_expires_at": str|None}."""
    try:
        with _db() as conn:
            ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT premium_expires_at, premium_readings_used, trial_expires_at FROM users WHERE user_id = %s",
                    (user_id,),
                )
                row = cur.fetchone()
                if not row:
                    return {"expires_at": None, "readings_used": 0, "trial_expires_at": None}
                return {
                    "expires_at": row[0],
                    "readings_used": row[1] or 0,
                    "trial_expires_at": row[2],
                }
    except psycopg2.Error as exc:
        raise DatabaseError(str(exc)) from exc


def set_premium_expires(user_id: int, expires_at: str) -> None:
    try:
        with _db() as conn:
            ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET premium_expires_at = %s WHERE user_id = %s",
                    (expires_at, user_id),
                )
    except psycopg2.Error as exc:
        raise DatabaseError(str(exc)) from exc


def set_trial_expires(user_id: int, expires_at: str) -> None:
    try:
        with _db() as conn:
            ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET trial_expires_at = %s WHERE user_id = %s",
                    (expires_at, user_id),
                )
    except psycopg2.Error as exc:
        raise DatabaseError(str(exc)) from exc


def increment_premium_readings(user_id: int) -> None:
    try:
        with _db() as conn:
            ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET premium_readings_used = COALESCE(premium_readings_used, 0) + 1 WHERE user_id = %s",
                    (user_id,),
                )
    except psycopg2.Error as exc:
        raise DatabaseError(str(exc)) from exc


def reset_premium_readings(user_id: int) -> None:
    try:
        with _db() as conn:
            ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET premium_readings_used = 0 WHERE user_id = %s",
                    (user_id,),
                )
    except psycopg2.Error as exc:
        raise DatabaseError(str(exc)) from exc


def get_expiring_premium_users(dates: List[str]) -> List[Dict[str, Any]]:
    if not dates:
        return []
    placeholders = ",".join(["%s"] * len(dates))
    try:
        with _db() as conn:
            ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT user_id, preferred_name, premium_expires_at FROM users WHERE premium_expires_at IN ({placeholders})",
                    dates,
                )
                rows = cur.fetchall()
                return [{"user_id": row[0], "preferred_name": row[1], "premium_expires_at": row[2]} for row in rows]
    except psycopg2.Error as exc:
        raise DatabaseError(str(exc)) from exc


def get_pair_rasklad_runes(
    db_path: str,
    user_id: int,
    partner_name: str,
    day: str,
    runes: List[Dict[str, Any]],
) -> Tuple[str, str, str]:
    import hashlib

    seed = hashlib.md5(f"{user_id}:{partner_name.lower()}:{day}".encode()).hexdigest()
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
            for j in range(total):
                if j not in used:
                    indices.append(j)
                    used.add(j)
                    if len(indices) == 3:
                        break
            break

    return runes[indices[0]]["name"], runes[indices[1]]["name"], runes[indices[2]]["name"]
