import asyncio
import os
import inspect
from functools import wraps

from core.logging import bot_logger
from core.session_manager import SessionUnavailable


def session_number_from_client(app_session) -> str | None:
    session_name = str(getattr(app_session, "name", "") or "")
    if not session_name:
        return None

    number = os.path.basename(session_name).replace(".session", "")
    return number or None


def _is_expected_stop_error(exc: Exception) -> bool:
    text = str(exc).lower()
    expected_markers = (
        "already terminated",
        "already disconnected",
        "can't disconnect an initialized client",
        "not been started yet",
        "already stopped",
        "client is stopped",
    )
    return any(marker in text for marker in expected_markers)


async def _disconnect_client(app_session) -> None:
    # Kurigram disconnect() is valid only for connected-not-initialized clients.
    if getattr(app_session, "is_initialized", False):
        return
    if not getattr(app_session, "is_connected", False):
        return

    disconnect_method = getattr(app_session, "disconnect", None)
    try:
        if callable(disconnect_method):
            await disconnect_method()
    except Exception as exc:
        if _is_expected_stop_error(exc):
            bot_logger.debug(f"Skip disconnect warning: {exc}")
            return
        raise RuntimeError("Failed to disconnect Telegram client") from None


async def stop_client(app_session) -> None:
    # Full stop for runtime removal.
    stop_method = getattr(app_session, "stop", None)
    try:
        if callable(stop_method):
            if "clear_handlers" in inspect.signature(stop_method).parameters:
                await stop_method(clear_handlers=False)
            else:
                await stop_method()
            return
    except Exception as exc:
        if _is_expected_stop_error(exc):
            bot_logger.debug(f"Skip stop_client warning: {exc}")
            await _disconnect_client(app_session)
            return
        raise RuntimeError("Failed to stop Telegram client") from None

    await _disconnect_client(app_session)


async def close_partial_client(client):
    await stop_client(client)
    storage = getattr(client, "storage", None)
    if not getattr(client, "is_connected", False) and getattr(storage, "conn", None) is not None:
        await storage.close()


async def start_client(client, *, connect_only=False):
    from loader import session_manager

    starter = client.connect if connect_only else client.start
    await session_manager.start(client, starter, lambda: close_partial_client(client))


async def start_all_clients(clients):
    results = await asyncio.gather(*(start_client(client) for client in clients), return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            bot_logger.error("Telegram client startup failed: %s", type(result).__name__)


def managed_session_handler(function):
    @wraps(function)
    async def wrapped(client, *args, **kwargs):
        from loader import session_manager

        try:
            return await session_manager.run(client, lambda: function(client, *args, **kwargs))
        except SessionUnavailable:
            return None
    return wrapped


async def run_client_operation(client, operation):
    from loader import session_manager

    return await session_manager.run(client, operation)


async def stop_all_clients(clear_runtime: bool = True, for_restart: bool = False) -> int:
    from loader import session_manager

    runtime_sessions = await session_manager.get_snapshot()
    stopped = 0
    failed = 0
    for app_session in runtime_sessions:
        try:
            # Restart must close initialized clients and their SQLite storage too.
            did_stop = await session_manager.stop(app_session, lambda: stop_client(app_session), remove=clear_runtime)
        except Exception:
            failed += 1
            bot_logger.error("Telegram client could not be stopped")
            continue
        stopped += int(did_stop)

    # Give Windows file handles a short grace period to release .session files.
    await asyncio.sleep(0.2)
    if failed:
        raise RuntimeError(f"Failed to stop {failed} Telegram client(s)")
    return stopped


async def remove_client_from_runtime(app_session) -> None:
    from loader import session_manager

    await session_manager.stop(app_session, lambda: stop_client(app_session))


async def stop_and_remove_session(number: str) -> bool:
    from loader import session_manager

    target = str(number or "")
    if not target:
        return False

    removed = False
    for app_session in await session_manager.get_snapshot():
        if session_number_from_client(app_session) == target:
            removed = await session_manager.stop(app_session, lambda: stop_client(app_session)) or removed

    return removed


async def is_session_running(number: str) -> bool:
    from loader import session_manager

    target = str(number or "")
    if not target:
        return False

    for app_session in await session_manager.get_snapshot():
        if session_number_from_client(app_session) != target:
            continue
        return await session_manager.is_available(app_session)

    return False


async def get_client_by_number(number: str):
    from loader import session_manager

    target = str(number or "")
    if not target:
        return None

    for app_session in await session_manager.get_snapshot():
        if session_number_from_client(app_session) == target:
            return app_session

    return None
