from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import re
import shutil
import tempfile


def session_paths(name: str) -> list[Path]:
    return [Path(f"{name}{suffix}") for suffix in ("", ".session", ".session-shm", ".session-wal", ".session-journal")]


def account_session_paths(number: str, root: Path = Path("data/session")) -> list[Path]:
    """Exact files of one account; a number prefix must never match another session."""
    if not re.fullmatch(r"\+?[0-9]+", str(number)):
        raise ValueError("Invalid account session number")
    root = root.resolve()
    paths = session_paths(str(root / str(number)))
    if any(path.is_symlink() or path.resolve().parent != root for path in paths):
        raise ValueError("Unsafe account session path")
    return paths


def remove_account_session_files(number: str, *, strict: bool = False) -> None:
    for path in account_session_paths(number):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            if strict:
                raise
            # Preserve existing best-effort cleanup; never broaden the file set.
            pass


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
