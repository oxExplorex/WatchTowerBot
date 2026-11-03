import asyncio
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.session_manager import SessionManager, SessionUnavailable


def client(name="offline"):
    return SimpleNamespace(name=name, is_connected=True, is_initialized=True)


@pytest.mark.asyncio
async def test_stop_cleans_operations_and_rejects_stale_snapshots_without_affecting_other_clients():
    manager = SessionManager()
    first, second = client("first"), client("second")
    await manager.extend([first, second])
    started = asyncio.Event()
    finish_other = asyncio.Event()
    order = []

    async def work():
        started.set()
        try:
            await asyncio.Future()
        finally:
            await asyncio.sleep(0)
            order.append("cleaned")

    async def stop():
        order.append("stopped")

    operation = asyncio.create_task(manager.run(first, work))
    other = asyncio.create_task(manager.run(second, finish_other.wait))
    await started.wait()
    assert await manager.stop(first, stop)
    with pytest.raises(SessionUnavailable):
        await operation
    assert order == ["cleaned", "stopped"] and not other.done()
    with pytest.raises(SessionUnavailable):
        await manager.run(first, work)
    finish_other.set()
    await other


@pytest.mark.asyncio
async def test_caller_cancellation_joins_operation_cleanup():
    manager = SessionManager()
    active = client()
    await manager.add(active)
    started, cleaned = asyncio.Event(), asyncio.Event()

    async def work():
        started.set()
        try:
            await asyncio.Future()
        finally:
            await asyncio.sleep(0)
            cleaned.set()

    operation = asyncio.create_task(manager.run(active, work))
    await started.wait()
    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert cleaned.is_set()
    assert await manager.is_available(active)


@pytest.mark.asyncio
async def test_concurrent_and_cancelled_stop_closes_once():
    manager = SessionManager()
    active = client()
    await manager.add(active)
    started, finish = asyncio.Event(), asyncio.Event()
    calls = []

    async def stop():
        calls.append("stop")
        started.set()
        await finish.wait()

    stopping = asyncio.create_task(manager.stop(active, stop))
    await started.wait()
    second = asyncio.create_task(manager.stop(active, stop))
    stopping.cancel()
    await asyncio.sleep(0)
    assert not stopping.done() and not await manager.is_available(active)
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await stopping
    assert await second is False
    assert calls == ["stop"] and await manager.count() == 0


@pytest.mark.asyncio
async def test_start_and_stop_are_serialized_and_starting_client_cannot_be_used():
    manager = SessionManager()
    active = client()
    active.is_initialized = active.is_connected = False
    await manager.add(active)
    started, finish = asyncio.Event(), asyncio.Event()
    order = []

    async def start():
        started.set()
        await finish.wait()
        active.is_initialized = active.is_connected = True
        order.append("started")

    async def stop():
        order.append("stopped")

    starting = asyncio.create_task(manager.start(active, start, AsyncMock()))
    await started.wait()
    with pytest.raises(SessionUnavailable):
        await manager.run(active, AsyncMock())
    stopping = asyncio.create_task(manager.stop(active, stop))
    finish.set()
    await asyncio.gather(starting, stopping)
    assert order == ["started", "stopped"]


@pytest.mark.asyncio
async def test_scan_can_retire_its_own_failed_client_without_waiting_for_itself():
    manager = SessionManager()
    active = client()
    await manager.add(active)

    async def scan():
        return await manager.stop(active, AsyncMock())

    async with asyncio.timeout(2):
        assert await manager.run(active, scan)
    assert await manager.count() == 0


@pytest.mark.asyncio
async def test_sdk_worker_survives_cancelled_callback_and_inherits_raw_identity(monkeypatch, offline_module):
    from pyrogram import Client
    from pyrogram.handlers import MessageHandler, RawUpdateHandler
    from pyrogram.types import Message
    import sys
    from types import ModuleType

    loader = ModuleType("loader")
    loader.session_manager = SessionManager()
    monkeypatch.setitem(sys.modules, "loader", loader)
    runtime = offline_module("core/session_runtime.py")
    updates = offline_module("core/message_updates.py")
    active = Client("offline", api_id=1, api_hash="synthetic", in_memory=True)
    active.is_initialized = active.is_connected = True
    await loader.session_manager.add(active)
    started = asyncio.Event()
    identities = []

    async def handle(client, message):
        identities.append(updates.current_update_identity(client))
        started.set()
        await asyncio.Future()

    class Packet:
        pts = 10

    async def parse(*args):
        return Message(id=12), MessageHandler

    active.dispatcher.groups = OrderedDict([
        (-100, [RawUpdateHandler(updates.remember_update_identity)]),
        (0, [MessageHandler(runtime.managed_session_handler(handle))]),
    ])
    active.dispatcher.update_parsers = {Packet: parse}
    worker = asyncio.create_task(active.dispatcher.handler_worker(asyncio.Lock()))
    await active.dispatcher.updates_queue.put((Packet(), {}, {}))

    async def stop():
        await active.dispatcher.updates_queue.put(None)
        await worker

    async with asyncio.timeout(2):
        await started.wait()
        await loader.session_manager.stop(active, stop)
    assert not worker.cancelled() and worker.done()
    assert identities == ["Packet:10"]


@pytest.mark.asyncio
async def test_real_sdk_stop_preserves_handlers_and_closes_storage(offline_module):
    from pyrogram import Client
    from pyrogram.handlers import MessageHandler

    runtime = offline_module("core/session_runtime.py")
    active = Client("offline", api_id=1, api_hash="synthetic", in_memory=True, workers=1)
    active.is_initialized = active.is_connected = True
    active.storage = SimpleNamespace(save=AsyncMock(), close=AsyncMock())
    connection = SimpleNamespace(stop=AsyncMock())
    active.session = connection
    active.dispatcher.groups = OrderedDict([(0, [MessageHandler(AsyncMock())])])
    worker = asyncio.create_task(active.dispatcher.handler_worker(asyncio.Lock()))
    active.dispatcher.handler_worker_tasks.append(worker)
    async with asyncio.timeout(2):
        await runtime.stop_client(active)
    assert active.dispatcher.groups and not active.is_connected and not active.is_initialized
    connection.stop.assert_awaited_once()
    active.storage.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelled_partial_start_disconnects_before_other_lifecycle_operations(monkeypatch, offline_module):
    import sys
    from types import ModuleType

    loader = ModuleType("loader")
    loader.session_manager = SessionManager()
    monkeypatch.setitem(sys.modules, "loader", loader)
    runtime = offline_module("core/session_runtime.py")
    active = client()
    active.is_connected = active.is_initialized = False
    started = asyncio.Event()

    async def start():
        active.is_connected = True
        started.set()
        await asyncio.Future()

    async def disconnect():
        active.is_connected = False

    active.start = start
    active.stop = AsyncMock(side_effect=ConnectionError("Client is already terminated"))
    active.disconnect = AsyncMock(side_effect=disconnect)
    await loader.session_manager.add(active)
    starting = asyncio.create_task(runtime.start_client(active))
    await started.wait()
    starting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await starting
    assert not active.is_connected and not await loader.session_manager.is_available(active)
    active.disconnect.assert_awaited_once()
