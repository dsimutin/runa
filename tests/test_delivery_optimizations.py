from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import bot


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
