"""Own temporary authorization clients independently of FSM progress."""
import asyncio
from pathlib import Path
import re

from core.session_files import session_paths
from core.session_runtime import close_partial_client


def _temporary_path(name):
    root = Path("data/session").resolve()
    path = Path(name).resolve()
    if path.parent != root or not re.fullmatch(r"_auth_\d+_\d+_[0-9a-f]{32}", path.name):
        raise ValueError("Invalid temporary session path")
    return path


async def _remove_files(base):
    paths = session_paths(str(base))
    if any(path.is_symlink() or path.resolve().parent != base.parent for path in paths):
        raise ValueError("Temporary session path must not use links")
    for path in paths:
        for attempt in range(3):
            try:
                path.unlink(missing_ok=True)
                break
            except PermissionError:
                if attempt == 2:
                    raise RuntimeError("Temporary session files could not be removed") from None
                await asyncio.sleep(0.2)


async def discard_session_files(name):
    await _remove_files(_temporary_path(name))


class TemporaryClients:
    def __init__(self):
        self._clients = {}
        self._locks = {}
        self._paused = False
        self._owners = {}

    def resume(self):
        self._paused = False

    def contains(self, client):
        return id(client) in self._clients

    def register(self, client, name, state=None):
        if self._paused:
            raise RuntimeError("Application is shutting down")
        self._clients[id(client)] = (client, _temporary_path(name), state)
        self.track(client)

    def track(self, client):
        if self._paused:
            raise RuntimeError("Application is shutting down")
        if id(client) in self._clients:
            self._owners.setdefault(id(client), set()).add(asyncio.current_task())

    async def disconnect(self, client):
        async with self._locks.setdefault(id(client), asyncio.Lock()):
            await close_partial_client(client)

    async def discard(self, client):
        async with self._locks.setdefault(id(client), asyncio.Lock()):
            await close_partial_client(client)
            entry = self._clients.get(id(client))
            if entry is not None:
                await _remove_files(entry[1])
                self._clients.pop(id(client), None)
                self._owners.pop(id(client), None)

    async def close_all(self):
        self._paused = True
        entries = list(self._clients.values())
        current = asyncio.current_task()
        tasks = {task for owners in self._owners.values() for task in owners
                 if task is not None and task is not current and not task.done()}
        for task in tasks:
            if not task.cancelling():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        failed = 0
        for client, _, state in entries:
            try:
                await self.discard(client)
                if state is not None:
                    await state.clear()
            except Exception:
                failed += 1
        if failed:
            raise RuntimeError(f"Failed to close {failed} temporary authorization client(s)")


auth_clients = TemporaryClients()
