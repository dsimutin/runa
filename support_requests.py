import sqlite3
from datetime import datetime
from typing import Any, Dict, List


class SupportRequestError(Exception):
    pass


def init_support_db(db_path: str) -> None:
    try:
        with sqlite3.connect(db_path, timeout=30) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS human_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    question TEXT NOT NULL,
                    palette TEXT NOT NULL DEFAULT 'light',
                    status TEXT NOT NULL DEFAULT 'new',
                    operator_id INTEGER,
                    operator_username TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS operators (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL,
                    registered_at TEXT NOT NULL
                )
                """
            )
    except sqlite3.Error as exc:
        raise SupportRequestError(str(exc)) from exc


def register_operator(db_path: str, user_id: int, username: str) -> None:
    now = datetime.utcnow().isoformat(timespec="seconds")
    try:
        with sqlite3.connect(db_path, timeout=30) as conn:
            init_support_db(db_path)
            conn.execute(
                """
                INSERT INTO operators (user_id, username, registered_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET username = excluded.username
                """,
                (user_id, username.lower(), now),
            )
    except sqlite3.Error as exc:
        raise SupportRequestError(str(exc)) from exc


def list_operator_ids(db_path: str, allowed_usernames: set[str]) -> List[int]:
    try:
        with sqlite3.connect(db_path, timeout=30) as conn:
            init_support_db(db_path)
            rows = conn.execute("SELECT user_id, username FROM operators").fetchall()
            return [row[0] for row in rows if row[1].lower() in allowed_usernames]
    except sqlite3.Error as exc:
        raise SupportRequestError(str(exc)) from exc


def create_request(db_path: str, user_id: int, question: str, palette: str) -> int:
    now = datetime.utcnow().isoformat(timespec="seconds")
    try:
        with sqlite3.connect(db_path, timeout=30) as conn:
            init_support_db(db_path)
            cursor = conn.execute(
                """
                INSERT INTO human_requests (user_id, question, palette, status, created_at, updated_at)
                VALUES (?, ?, ?, 'new', ?, ?)
                """,
                (user_id, question, palette, now, now),
            )
            return int(cursor.lastrowid)
    except sqlite3.Error as exc:
        raise SupportRequestError(str(exc)) from exc


def get_request(db_path: str, request_id: int) -> Dict[str, Any] | None:
    try:
        with sqlite3.connect(db_path, timeout=30) as conn:
            init_support_db(db_path)
            row = conn.execute(
                """
                SELECT id, user_id, question, palette, status, operator_id, operator_username, created_at, updated_at
                FROM human_requests
                WHERE id = ?
                """,
                (request_id,),
            ).fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "user_id": row[1],
                "question": row[2],
                "palette": row[3],
                "status": row[4],
                "operator_id": row[5],
                "operator_username": row[6],
                "created_at": row[7],
                "updated_at": row[8],
            }
    except sqlite3.Error as exc:
        raise SupportRequestError(str(exc)) from exc


def get_latest_open_request(db_path: str) -> Dict[str, Any] | None:
    try:
        with sqlite3.connect(db_path, timeout=30) as conn:
            init_support_db(db_path)
            row = conn.execute(
                """
                SELECT id
                FROM human_requests
                WHERE status IN ('new', 'claimed', 'open')
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            if not row:
                return None
            return get_request(db_path, int(row[0]))
    except sqlite3.Error as exc:
        raise SupportRequestError(str(exc)) from exc


def claim_request(db_path: str, request_id: int, operator_id: int, operator_username: str) -> Dict[str, Any] | None:
    now = datetime.utcnow().isoformat(timespec="seconds")
    try:
        with sqlite3.connect(db_path, timeout=30) as conn:
            init_support_db(db_path)
            conn.execute(
                """
                UPDATE human_requests
                SET status = 'claimed', operator_id = ?, operator_username = ?, updated_at = ?
                WHERE id = ? AND status IN ('new', 'claimed')
                """,
                (operator_id, operator_username, now, request_id),
            )
        return get_request(db_path, request_id)
    except sqlite3.Error as exc:
        raise SupportRequestError(str(exc)) from exc


def close_request(db_path: str, request_id: int) -> None:
    now = datetime.utcnow().isoformat(timespec="seconds")
    try:
        with sqlite3.connect(db_path, timeout=30) as conn:
            init_support_db(db_path)
            conn.execute("UPDATE human_requests SET status = 'answered', updated_at = ? WHERE id = ?", (now, request_id))
    except sqlite3.Error as exc:
        raise SupportRequestError(str(exc)) from exc
