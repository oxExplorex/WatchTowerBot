from __future__ import annotations

import os
import platform
import sys
from pathlib import Path


def is_windows() -> bool:
    return platform.system().lower().startswith("win")


def start_script_name() -> str:
    return "start.bat" if is_windows() else "start.sh"


def update_script_name() -> str:
    return "update.bat" if is_windows() else "update.sh"


def restart_current_process() -> None:
    python_executable = sys.executable
    main_script = str(Path("main.py").resolve())
    os.execv(python_executable, [python_executable, main_script])


async def restart_with_clients() -> None:
    from core.logging import bot_logger
    from core.auth_sessions import auth_clients
    from core.session_runtime import start_client, stop_all_clients
    from loader import session_manager

    clients = await session_manager.get_snapshot()
    previous_states = [
        (client, bool(getattr(client, "is_initialized", False)), bool(getattr(client, "is_connected", False)))
        for client in clients
    ]
    try:
        await auth_clients.close_all()
        # Keep registry membership until exec succeeds, allowing recovery on error.
        await stop_all_clients(clear_runtime=False, for_restart=True)
        restart_current_process()
    except BaseException:
        for client, was_initialized, was_connected in previous_states:
            try:
                if was_initialized and not getattr(client, "is_initialized", False):
                    await start_client(client)
                elif was_connected and not getattr(client, "is_connected", False):
                    await start_client(client, connect_only=True)
            except Exception as exc:
                bot_logger.error("Could not restore Telegram client after failed restart: %s", type(exc).__name__)
        auth_clients.resume()
        raise
