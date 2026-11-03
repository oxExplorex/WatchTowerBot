from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
from uuid import uuid4


DEFAULT_SESSION_DIRECTORY = Path(__file__).resolve().parents[1] / "data" / "session"


def migrate_legacy_session(path: Path) -> bool:
    """Keep the pyrofork v4 bridge: its schema version differs from Kurigram v4.

    Only run with the bot stopped. Preserve the original SQLite database through
    SQLite's backup API before changing metadata, peers or usernames.
    """
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=rw", uri=True, timeout=2)) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if not {"sessions", "peers", "version"}.issubset(tables):
            return False
        peer_columns = {row[1] for row in connection.execute("PRAGMA table_info(peers)")}
        if "username" not in peer_columns or "usernames" in tables:
            return False
        version = connection.execute("SELECT number FROM version").fetchone()
        session_columns = {row[1] for row in connection.execute("PRAGMA table_info(sessions)")}
        expected_columns = {"dc_id", "api_id", "test_mode", "auth_key", "date", "user_id", "is_bot"}
        if version != (4,) or "update_state" not in tables or session_columns != expected_columns:
            raise RuntimeError("Unsupported legacy Telegram session schema; automatic conversion stopped")

        backup_path = path.with_name(f"{path.name}.pyrofork-v4.{uuid4().hex}.bak")
        backup = sqlite3.connect(backup_path)
        try:
            connection.backup(backup)
        finally:
            backup.close()

        with connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("CREATE TABLE usernames (id INTEGER, username TEXT, FOREIGN KEY (id) REFERENCES peers(id))")
            connection.execute("CREATE INDEX idx_usernames_id ON usernames (id)")
            connection.execute("CREATE INDEX idx_usernames_username ON usernames (username)")
            connection.execute("INSERT INTO usernames (id, username) SELECT id, username FROM peers WHERE username IS NOT NULL")
            connection.execute("UPDATE version SET number = 6")
        return True


def migrate_legacy_sessions(directory: Path = DEFAULT_SESSION_DIRECTORY) -> int:
    migrated = sum(migrate_legacy_session(path) for path in sorted(directory.glob("*.session")))
    if migrated:
        print(f"Migrated {migrated} legacy Telegram sessions; original backups are beside the session files", flush=True)
    return migrated


if __name__ == "__main__":
    migrate_legacy_sessions()
