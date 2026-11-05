"""Read-only admission check before the SDK opens a session from an old fork."""
from contextlib import closing
from pathlib import Path
import sqlite3


class SessionSchemaError(RuntimeError):
    def __init__(self, columns=()):
        self.columns = tuple(sorted(columns))
        super().__init__("Legacy Telegram session requires deletion and manual authorization")


def validate_session_schema(path: Path) -> None:
    # Never convert or delete a session during startup. In particular, Kurigram's
    # own v4 upgrade cannot distinguish pyrofork's incompatible version number.
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=2)) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        peers = {row[1] for row in connection.execute("PRAGMA table_info(peers)")}
        usernames = {row[1] for row in connection.execute("PRAGMA table_info(usernames)")}
        version = connection.execute("SELECT number FROM version").fetchone() if "version" in tables else None
        if ("username" in peers or ("usernames" in tables and usernames != {"id", "username"})
                or (version == (4,) and "update_state" in tables)):
            raise SessionSchemaError(usernames)
