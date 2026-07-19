"""Durable python-telegram-bot user state backed by Neon PostgreSQL."""

from __future__ import annotations

import asyncio
from typing import Any

from telegram.ext import BasePersistence, PersistenceInput

from database import delete_user_state, load_user_state, save_user_state


class NeonPersistence(BasePersistence[dict, dict, dict]):
    """Persist only ``context.user_data``; other PTB stores are not used."""

    def __init__(self) -> None:
        super().__init__(
            store_data=PersistenceInput(
                bot_data=False,
                chat_data=False,
                user_data=True,
                callback_data=False,
            ),
            # Interactive updates are persisted explicitly inside the webhook
            # request. This long interval is only a safety net.
            update_interval=3600,
        )
        self._loaded_user_ids: set[int] = set()
        self._load_locks: dict[int, asyncio.Lock] = {}

    async def get_user_data(self) -> dict[int, dict[str, Any]]:
        # Loading every user's state here made Cloud Run startup proportional
        # to the entire user table and blocked /health on a sleeping Neon DB.
        return {}

    async def refresh_user_data(self, user_id: int, user_data: dict[str, Any]) -> None:
        if user_id in self._loaded_user_ids:
            return
        lock = self._load_locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            if user_id in self._loaded_user_ids:
                return
            persisted = await asyncio.to_thread(load_user_state, user_id)
            user_data.clear()
            user_data.update(persisted)
            self._loaded_user_ids.add(user_id)
            self._load_locks.pop(user_id, None)

    async def update_user_data(self, user_id: int, data: dict[str, Any]) -> None:
        await asyncio.to_thread(save_user_state, user_id, dict(data))
        self._loaded_user_ids.add(user_id)

    async def drop_user_data(self, user_id: int) -> None:
        await asyncio.to_thread(delete_user_state, user_id)
        self._loaded_user_ids.discard(user_id)
        self._load_locks.pop(user_id, None)

    async def get_chat_data(self) -> dict[int, dict]:
        return {}

    async def update_chat_data(self, chat_id: int, data: dict) -> None:
        return None

    async def refresh_chat_data(self, chat_id: int, chat_data: dict) -> None:
        return None

    async def drop_chat_data(self, chat_id: int) -> None:
        return None

    async def get_bot_data(self) -> dict:
        return {}

    async def update_bot_data(self, data: dict) -> None:
        return None

    async def refresh_bot_data(self, bot_data: dict) -> None:
        return None

    async def get_callback_data(self):
        return None

    async def update_callback_data(self, data) -> None:
        return None

    async def get_conversations(self, name: str) -> dict:
        return {}

    async def update_conversation(self, name: str, key: tuple, new_state: object) -> None:
        return None

    async def flush(self) -> None:
        return None
