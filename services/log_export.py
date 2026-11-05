"""Export the active run's log, falling back to the latest file when needed."""
import logging
from pathlib import Path

def latest_log_file(directory=None):
    if directory is None:
        from core.logging import bot_logger
        for handler in bot_logger.handlers:
            if isinstance(handler, logging.FileHandler):
                handler.flush()
                path = Path(handler.baseFilename)
                if not path.is_symlink() and path.is_file():
                    return path.resolve()
        from data.config import path_logs
        directory = Path(path_logs.format(d="current")).parent
    root = Path(directory).resolve()
    candidates = [path for pattern in ("*.log", "*.txt") for path in root.glob(pattern)
                  if not path.is_symlink() and path.is_file() and path.resolve().parent == root]
    if not candidates:
        raise FileNotFoundError("No regular log files")
    return max(candidates, key=lambda entry: entry.stat().st_mtime_ns)
