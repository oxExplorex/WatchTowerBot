import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message

class AlbumMiddleware(BaseMiddleware):
    def __init__(self, latency: float = 0.1):
        self.latency = latency
        self.album_data: dict[tuple[int | None, int, str], list[Message]] = {}

    async def __call__(
        self, handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        message: Message, data: dict[str, Any],
    ) -> Any:
        if not message.media_group_id:
            return await handler(message, data)
        key = (getattr(message.bot, "id", None), message.chat.id, message.media_group_id)
        if key in self.album_data:
            self.album_data[key].append(message)
            return None
        album = self.album_data[key] = [message]
        try:
            await asyncio.sleep(self.latency)
            return await handler(message, {**data, "album": album})
        finally:
            self.album_data.pop(key, None)
