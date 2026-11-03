from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import tempfile


def session_paths(name: str) -> list[Path]:
    return [Path(f"{name}{suffix}") for suffix in ("", ".session", ".session-shm", ".session-wal", ".session-journal")]


@contextmanager
def replace_session_files(temporary_name: str, final_name: str):
    """Replace a disconnected session; restore its files if saving the account fails.

    Both clients must be disconnected before entering this context. Small renames
    stay synchronous so cancellation cannot race with a still-running file thread.
    """
    if not Path(f"{temporary_name}.session").is_file():
        raise FileNotFoundError("Authorized temporary session is missing")
    final_paths = session_paths(final_name)
    backup = Path(tempfile.mkdtemp(prefix="_session_backup_", dir=final_paths[0].parent))
    saved: list[tuple[Path, Path]] = []
    installed: list[Path] = []
    try:
        for destination in final_paths:
            if destination.exists():
                preserved = backup / destination.name
                os.replace(destination, preserved)
                saved.append((destination, preserved))
        for source, destination in zip(session_paths(temporary_name), final_paths):
            if source.exists():
                os.replace(source, destination)
                installed.append(destination)
        yield
    except BaseException:
        for destination in reversed(installed):
            destination.unlink(missing_ok=True)
        for destination, preserved in reversed(saved):
            os.replace(preserved, destination)
        # If restoration fails above, retain the backup for recovery.
        shutil.rmtree(backup, ignore_errors=True)
        raise
    else:
        shutil.rmtree(backup, ignore_errors=True)
