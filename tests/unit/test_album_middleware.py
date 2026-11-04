import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from middlewares.media_group import AlbumMiddleware


def message(chat_id):
    return SimpleNamespace(bot=SimpleNamespace(id=1), chat=SimpleNamespace(id=chat_id), media_group_id="same-id")


@pytest.mark.asyncio
async def test_albums_are_collected_once_and_isolated_between_chats_and_instances():
    middleware = AlbumMiddleware(latency=0)
    handler = AsyncMock()
    messages = [message(1), message(1), message(2)]
    await asyncio.gather(*(middleware(handler, item, {}) for item in messages))
    assert handler.await_count == 2
    assert [len(call.args[1]["album"]) for call in handler.await_args_list] == [2, 1]
    assert middleware.album_data == {}
    assert middleware.album_data is not AlbumMiddleware().album_data


@pytest.mark.asyncio
async def test_handler_failure_releases_album_buffer():
    middleware = AlbumMiddleware(latency=0)
    with pytest.raises(RuntimeError):
        await middleware(AsyncMock(side_effect=RuntimeError("offline")), message(1), {})
    assert middleware.album_data == {}


@pytest.mark.asyncio
async def test_cancellation_during_collection_releases_album_buffer():
    middleware = AlbumMiddleware(latency=60)
    handler = AsyncMock()
    task = asyncio.create_task(middleware(handler, message(1), {}))
    await asyncio.sleep(0)
    assert middleware.album_data
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert middleware.album_data == {}
    handler.assert_not_awaited()
