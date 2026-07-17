from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import psycopg2

import bot
import database
import neon_persistence
from spread_engine_approved import spread_page_callback


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


@pytest.mark.asyncio
async def test_neon_persistence_refreshes_and_saves_user_state():
    persistence = neon_persistence.NeonPersistence()
    user_data = {"state": "waiting_rasklad"}

    with (
        patch(
            "neon_persistence.load_all_user_states",
            return_value={42: {"state": "waiting_rasklad"}},
        ),
        patch("neon_persistence.save_user_state") as save_state,
    ):
        loaded = await persistence.get_user_data()
        assert loaded == {42: {"state": "waiting_rasklad"}}
        await persistence.refresh_user_data(42, user_data)
        assert user_data == {"state": "waiting_rasklad"}
        user_data["spread_pages"] = {"token": "abc", "pages": ["one", "two"]}
        await persistence.update_user_data(42, user_data)

    save_state.assert_called_once_with(42, user_data)


@pytest.mark.asyncio
async def test_spread_navigation_edits_photo_caption_instead_of_sending_new_message():
    query = SimpleNamespace(
        data="spread_page:abc123:1",
        answer=AsyncMock(),
        edit_message_caption=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=42))
    context = SimpleNamespace(
        user_data={
            "spread_pages": {
                "token": "abc123",
                "pages": ["Первая", "Вторая"],
                "media": True,
            }
        },
        bot=SimpleNamespace(send_message=AsyncMock()),
    )

    await spread_page_callback(update, context)

    query.edit_message_caption.assert_awaited_once()
    query.edit_message_text.assert_not_awaited()
