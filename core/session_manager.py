"""
Session manager for Pyrogram clients.

Provides synchronized access to the client collection within one event loop.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyrogram import Client


class SessionUnavailable(RuntimeError):
    """The client is absent, starting, or being stopped."""


class SessionManager:
    """
    Async-safe registry for Pyrogram client sessions.

    Serializes lifecycle callbacks and owns cancellable client operations.
    Snapshots are for iteration; API calls must go through run().
    """

    def __init__(self) -> None:
        self._clients: list[Client] = []
        self._lock = asyncio.Lock()
        self._lifecycle_locks: dict[int, asyncio.Lock] = {}
        self._closing: set[int] = set()
        self._operations: dict[int, set[asyncio.Task]] = {}

    def _lifecycle_lock(self, client):
        return self._lifecycle_locks.setdefault(id(client), asyncio.Lock())

    async def is_available(self, client):
        async with self._lock:
            return (client in self._clients and id(client) not in self._closing
                    and bool(getattr(client, "is_initialized", False))
                    and bool(getattr(client, "is_connected", False)))

    async def run(self, client, operation: Callable[[], Awaitable]):
        """Own a cancellable operation without cancelling the SDK dispatcher worker."""
        async with self._lock:
            if (client not in self._clients or id(client) in self._closing
                    or not getattr(client, "is_initialized", True)
                    or not getattr(client, "is_connected", True)):
                raise SessionUnavailable()
            task = asyncio.create_task(operation())
            self._operations.setdefault(id(client), set()).add(task)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if asyncio.current_task().cancelling():
                raise
            raise SessionUnavailable() from None
        finally:
            async with self._lock:
                tasks = self._operations.get(id(client))
                if tasks is not None:
                    tasks.discard(task)
                    if not tasks:
                        self._operations.pop(id(client), None)

    async def start(self, client, starter, cleanup):
        async with self._lifecycle_lock(client):
            async with self._lock:
                if client not in self._clients:
                    raise SessionUnavailable()
                if id(client) not in self._closing and getattr(client, "is_initialized", False):
                    return
                self._closing.add(id(client))
            try:
                if getattr(client, "is_connected", False) or getattr(client, "is_initialized", False):
                    await cleanup()
                await starter()
            except BaseException:
                await cleanup()
                raise
            else:
                async with self._lock:
                    self._closing.discard(id(client))

    async def stop(self, client, stopper, *, remove=True):
        async with self._lifecycle_lock(client):
            async with self._lock:
                if client not in self._clients:
                    return False
                self._closing.add(id(client))
                current = asyncio.current_task()
                tasks = [task for task in self._operations.get(id(client), ()) if task is not current]
            async def finish():
                for task in tasks:
                    if not task.cancelling():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await stopper()
                if remove:
                    await self.remove(client)

            closing = asyncio.create_task(finish())
            try:
                await asyncio.shield(closing)
            except asyncio.CancelledError:
                await closing
                raise
            return True

    async def add(self, client: Client) -> None:
        """
        Add a client session to the manager.

        Args:
            client: Pyrogram Client instance to add
        """
        async with self._lock:
            if id(client) in self._closing:
                raise SessionUnavailable()
            if client not in self._clients:
                self._clients.append(client)

    async def remove(self, client: Client) -> bool:
        """
        Remove a client session from the manager.

        Args:
            client: Pyrogram Client instance to remove

        Returns:
            True if client was removed, False if not found
        """
        async with self._lock:
            if client in self._clients:
                self._clients.remove(client)
                self._closing.discard(id(client))
                return True
            return False

    async def get_snapshot(self) -> list[Client]:
        """
        Get a snapshot copy of all active client sessions.

        Returns a copy to prevent external modifications affecting
        the internal collection during iteration.

        Returns:
            List copy of all active Client instances
        """
        async with self._lock:
            return list(self._clients)

    async def clear(self) -> None:
        """
        Remove all client sessions from the manager.
        """
        async with self._lock:
            self._clients.clear()
            self._closing.clear()

    async def count(self) -> int:
        """
        Get the number of active client sessions.

        Returns:
            Number of clients currently managed
        """
        async with self._lock:
            return len(self._clients)

    async def extend(self, clients: list[Client]) -> None:
        """
        Add multiple client sessions to the manager.

        Args:
            clients: List of Pyrogram Client instances to add
        """
        async with self._lock:
            for client in clients:
                if client not in self._clients:
                    self._clients.append(client)
