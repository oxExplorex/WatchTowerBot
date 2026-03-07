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