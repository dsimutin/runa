from datetime import datetime
from typing import Any, Dict, List

import psycopg2

from database import _db


class SupportRequestError(Exception):
    pass


def _ensure_support_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS human_requests (
                id               BIGSERIAL PRIMARY KEY,
                user_id          BIGINT    NOT NULL,
                question         TEXT      NOT NULL,
                palette          TEXT      NOT NULL DEFAULT 'light',
                status           TEXT      NOT NULL DEFAULT 'new',
                operator_id      BIGINT,
                operator_username TEXT,
                created_at       TEXT      NOT NULL,
                updated_at       TEXT      NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS operators (
                user_id      BIGINT PRIMARY KEY,
                username     TEXT   NOT NULL,
                registered_at TEXT  NOT NULL
            )
            """
        )


def init_support_db() -> None:
    try:
        with _db() as conn:
            _ensure_support_schema(conn)
    except psycopg2.Error as exc:
        raise SupportRequestError(str(exc)) from exc


def register_operator(user_id: int, username: str) -> None:
    now = datetime.utcnow().isoformat(timespec="seconds")
    try:
        with _db() as conn:
            _ensure_support_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO operators (user_id, username, registered_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username
                    """,
                    (user_id, username.lower(), now),
                )
    except psycopg2.Error as exc:
        raise SupportRequestError(str(exc)) from exc


def list_operator_ids(allowed_usernames: set) -> List[int]:
    try:
        with _db() as conn:
            _ensure_support_schema(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT user_id, username FROM operators")
                rows = cur.fetchall()
                return [row[0] for row in rows if row[1].lower() in allowed_usernames]
    except psycopg2.Error as exc:
        raise SupportRequestError(str(exc)) from exc


def create_request(user_id: int, question: str, palette: str) -> int:
    now = datetime.utcnow().isoformat(timespec="seconds")
    try:
        with _db() as conn:
            _ensure_support_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO human_requests (user_id, question, palette, status, created_at, updated_at)
                    VALUES (%s, %s, %s, 'new', %s, %s)
                    RETURNING id
                    """,
                    (user_id, question, palette, now, now),
                )
                return int(cur.fetchone()[0])
    except psycopg2.Error as exc:
        raise SupportRequestError(str(exc)) from exc


def get_request(request_id: int) -> Dict[str, Any] | None:
    try:
        with _db() as conn:
            _ensure_support_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, user_id, question, palette, status,
                           operator_id, operator_username, created_at, updated_at
                    FROM human_requests
                    WHERE id = %s
                    """,
                    (request_id,),
                )
                row = cur.fetchone()
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
    except psycopg2.Error as exc:
        raise SupportRequestError(str(exc)) from exc


def get_latest_open_request() -> Dict[str, Any] | None:
    try:
        with _db() as conn:
            _ensure_support_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id FROM human_requests
                    WHERE status IN ('new', 'claimed', 'open')
                    ORDER BY id DESC
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
                if not row:
                    return None
        return get_request(int(row[0]))
    except psycopg2.Error as exc:
        raise SupportRequestError(str(exc)) from exc


def claim_request(request_id: int, operator_id: int, operator_username: str) -> Dict[str, Any] | None:
    now = datetime.utcnow().isoformat(timespec="seconds")
    try:
        with _db() as conn:
            _ensure_support_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE human_requests
                    SET status = 'claimed', operator_id = %s, operator_username = %s, updated_at = %s
                    WHERE id = %s AND status IN ('new', 'claimed')
                    """,
                    (operator_id, operator_username, now, request_id),
                )
        return get_request(request_id)
    except psycopg2.Error as exc:
        raise SupportRequestError(str(exc)) from exc


def close_request(request_id: int) -> None:
    now = datetime.utcnow().isoformat(timespec="seconds")
    try:
        with _db() as conn:
            _ensure_support_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE human_requests SET status = 'answered', updated_at = %s WHERE id = %s",
                    (now, request_id),
                )
    except psycopg2.Error as exc:
        raise SupportRequestError(str(exc)) from exc
