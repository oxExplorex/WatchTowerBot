"""
Tests for core/session_manager.py
"""
from __future__ import annotations

import asyncio
import types

import pytest

from core.session_manager import SessionManager


@pytest.mark.asyncio
async def test_session_manager_add():
    manager = SessionManager()
    client = types.SimpleNamespace(name="test_client")

    await manager.add(client)
    snapshot = await manager.get_snapshot()

    assert len(snapshot) == 1
    assert snapshot[0] is client


@pytest.mark.asyncio
async def test_session_manager_add_duplicate():
    manager = SessionManager()
    client = types.SimpleNamespace(name="test_client")

    await manager.add(client)
    await manager.add(client)  # Add same client twice
    snapshot = await manager.get_snapshot()

    assert len(snapshot) == 1  # Should only contain one instance


@pytest.mark.asyncio
async def test_session_manager_remove():
    manager = SessionManager()
    client = types.SimpleNamespace(name="test_client")

    await manager.add(client)
    removed = await manager.remove(client)
    snapshot = await manager.get_snapshot()

    assert removed is True
    assert len(snapshot) == 0


@pytest.mark.asyncio
async def test_session_manager_remove_nonexistent():
    manager = SessionManager()
    client = types.SimpleNamespace(name="test_client")

    removed = await manager.remove(client)

    assert removed is False


@pytest.mark.asyncio
async def test_session_manager_get_snapshot_returns_copy():
    manager = SessionManager()
    client1 = types.SimpleNamespace(name="client1")
    client2 = types.SimpleNamespace(name="client2")

    await manager.add(client1)
    snapshot1 = await manager.get_snapshot()

    await manager.add(client2)
    snapshot2 = await manager.get_snapshot()

    # First snapshot should not be affected by later additions
    assert len(snapshot1) == 1
    assert len(snapshot2) == 2


@pytest.mark.asyncio
async def test_session_manager_clear():
    manager = SessionManager()
    client1 = types.SimpleNamespace(name="client1")
    client2 = types.SimpleNamespace(name="client2")

    await manager.add(client1)
    await manager.add(client2)
    await manager.clear()
    snapshot = await manager.get_snapshot()

    assert len(snapshot) == 0


@pytest.mark.asyncio
async def test_session_manager_count():
    manager = SessionManager()
    client1 = types.SimpleNamespace(name="client1")
    client2 = types.SimpleNamespace(name="client2")

    assert await manager.count() == 0

    await manager.add(client1)
    assert await manager.count() == 1

    await manager.add(client2)
    assert await manager.count() == 2

    await manager.remove(client1)
    assert await manager.count() == 1


@pytest.mark.asyncio
async def test_session_manager_extend():
    manager = SessionManager()
    client1 = types.SimpleNamespace(name="client1")
    client2 = types.SimpleNamespace(name="client2")
    client3 = types.SimpleNamespace(name="client3")

    await manager.add(client1)
    await manager.extend([client2, client3])
    snapshot = await manager.get_snapshot()

    assert len(snapshot) == 3
    assert client1 in snapshot
    assert client2 in snapshot
    assert client3 in snapshot


@pytest.mark.asyncio
async def test_session_manager_extend_with_duplicates():
    manager = SessionManager()
    client1 = types.SimpleNamespace(name="client1")
    client2 = types.SimpleNamespace(name="client2")

    await manager.add(client1)
    await manager.extend([client1, client2])  # client1 already exists
    snapshot = await manager.get_snapshot()

    assert len(snapshot) == 2  # Should not duplicate client1


@pytest.mark.asyncio
async def test_session_manager_concurrent_access():
    """Test that concurrent add/remove operations are thread-safe."""
    manager = SessionManager()
    clients = [types.SimpleNamespace(name=f"client{i}") for i in range(10)]

    async def add_clients():
        for client in clients:
            await manager.add(client)
            await asyncio.sleep(0)  # Yield control

    async def remove_clients():
        await asyncio.sleep(0.001)  # Let some adds happen first
        for client in clients[:5]:
            await manager.remove(client)
            await asyncio.sleep(0)  # Yield control

    await asyncio.gather(add_clients(), remove_clients())
    snapshot = await manager.get_snapshot()

    # Should have 5 clients remaining (10 added - 5 removed)
    assert len(snapshot) == 5
    # Verify correct clients remain
    for client in clients[5:]:
        assert client in snapshot
