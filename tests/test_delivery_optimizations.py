from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import psycopg2

import bot
import database


@pytest.mark.asyncio
async def test_send_cached_photo_uploads_once_then_reuses_file_id(tmp_path: Path):
    image = tmp_path / "card.jpg"
    image.write_bytes(b"small-test-image")
    send_photo = AsyncMock(
        return_value=SimpleNamespace(photo=[SimpleNamespace(file_id="telegram-file-id")])
    )
    bot._telegram_file_ids.clear()

    with (
        patch("database.get_telegram_file_id", return_value=None),
        patch("database.set_telegram_file_id") as save_file_id,
    ):
        await bot.send_cached_photo(send_photo, str(image), chat_id=1)
        await bot.send_cached_photo(send_photo, str(image), chat_id=1)

    first_photo = send_photo.await_args_list[0].kwargs["photo"]
    second_photo = send_photo.await_args_list[1].kwargs["photo"]
    assert hasattr(first_photo, "read")
    assert second_photo == "telegram-file-id"
    save_file_id.assert_called_once()


def test_generated_collage_cache_key_survives_mtime_change(tmp_path: Path):
    collage = tmp_path / "runa-spread-content-digest.jpg"
    collage.write_bytes(b"same-content")
    first = bot._image_asset_key(str(collage))
    collage.touch()
    second = bot._image_asset_key(str(collage))
    assert first == second


def test_database_context_replaces_stale_neon_connection():
    class StaleCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, _query):
            raise psycopg2.OperationalError("SSL connection has been closed unexpectedly")

    class Connection:
        def __init__(self, stale=False):
            self.stale = stale
            self.committed = False

        def cursor(self):
            return StaleCursor()

        def commit(self):
            self.committed = True

        def close(self):
            pass

    stale = Connection(stale=True)
    fresh = Connection()

    class Pool:
        def __init__(self):
            self.connections = [stale, fresh]
            self.returned = []

        def getconn(self):
            return self.connections.pop(0)

        def putconn(self, conn, close=False):
            self.returned.append((conn, close))

    pool = Pool()
    database._connection_last_used.clear()
    with patch("database._get_pool", return_value=pool):
        with database._db() as conn:
            assert conn is fresh

    assert pool.returned[0] == (stale, True)
    assert pool.returned[-1] == (fresh, False)
    assert fresh.committed
