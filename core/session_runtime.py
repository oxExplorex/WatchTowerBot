import os
import traceback

from core.logging import bot_logger


def session_number_from_client(app_session) -> str | None:
    session_name = str(getattr(app_session, "name", "") or "")
    if not session_name:
        return None

    number = os.path.basename(session_name).replace(".session", "")
    return number or None


async def stop_client(app_session) -> None:
    try:
        if getattr(app_session, "is_initialized", False):
            await app_session.stop()
            return
        if getattr(app_session, "is_connected", False):
            await app_session.disconnect()
    except Exception:
        bot_logger.error(traceback.format_exc())


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
