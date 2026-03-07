import asyncio
import os

from core.logging import bot_logger


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
        "not been started yet",
        "already stopped",
        "client is stopped",
    )
    return any(marker in text for marker in expected_markers)


async def stop_client(app_session) -> None:
    try:
        stop_method = getattr(app_session, "stop", None)
        if callable(stop_method):
            await stop_method()

        disconnect_method = getattr(app_session, "disconnect", None)
        if callable(disconnect_method):
            await disconnect_method()
    except Exception as exc:
        if _is_expected_stop_error(exc):
            bot_logger.debug(f"Skip stop_client warning: {exc}")
            return
        bot_logger.exception("stop_client failed")


async def stop_all_clients(clear_runtime: bool = True) -> int:
    from loader import apps_session

    stopped = 0
    for app_session in list(apps_session):
        await stop_client(app_session)
        stopped += 1

    if clear_runtime:
        apps_session.clear()

    # Give Windows file handles a short grace period to release .session files.
    await asyncio.sleep(0.2)
    return stopped


async def remove_client_from_runtime(app_session) -> None:
    from loader import apps_session

    await stop_client(app_session)

    if app_session in apps_session:
        apps_session.remove(app_session)


async def stop_and_remove_session(number: str) -> bool:
    from loader import apps_session

    target = str(number or "")
    if not target:
        return False

    removed = False
    for app_session in list(apps_session):
        if session_number_from_client(app_session) == target:
            await stop_client(app_session)
            if app_session in apps_session:
                apps_session.remove(app_session)
            removed = True

    return removed


def is_session_running(number: str) -> bool:
    from loader import apps_session

    target = str(number or "")
    if not target:
        return False

    for app_session in apps_session:
        if session_number_from_client(app_session) != target:
            continue
        if getattr(app_session, "is_initialized", False) or getattr(app_session, "is_connected", False):
            return True

    return False


def get_client_by_number(number: str):
    from loader import apps_session

    target = str(number or "")
    if not target:
        return None

    for app_session in apps_session:
        if session_number_from_client(app_session) == target:
            return app_session

    return None
