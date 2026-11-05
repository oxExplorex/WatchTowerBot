from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
from uuid import uuid4


DEFAULT_SESSION_DIRECTORY = Path(__file__).resolve().parents[1] / "data" / "session"


class SessionSchemaError(RuntimeError):
    """Only schema metadata, never session row values or credentials."""

    def __init__(self, columns):
        self.columns = tuple(sorted(columns))
        super().__init__("Unsupported legacy Telegram username schema; automatic conversion stopped")


def migrate_legacy_session(path: Path) -> bool:
    """Keep the pyrofork v4 bridge: its schema version differs from Kurigram v4.

    Only run with this client stopped. Preserve the original SQLite database through
    SQLite's backup API before changing metadata, peers or usernames.
    A failed earlier migration may already have created usernames while leaving
    version 4. Its existence alone does not mean this bridge has completed.
    """
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=rw", uri=True, timeout=2)) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if not {"sessions", "peers", "version"}.issubset(tables):
            return False
        peer_columns = {row[1] for row in connection.execute("PRAGMA table_info(peers)")}
        has_legacy_names = "username" in peer_columns
        partial_modern = {"usernames", "update_state"}.issubset(tables)
        if not has_legacy_names and not partial_modern:
            return False
        version = connection.execute("SELECT number FROM version").fetchone()
        if "usernames" in tables and version != (4,):
            return False  # Only repair the v4 collision; other upgrades belong to Kurigram.
        session_columns = {row[1] for row in connection.execute("PRAGMA table_info(sessions)")}
        expected_columns = {"dc_id", "api_id", "test_mode", "auth_key", "date", "user_id", "is_bot"}
        expected_peers = {"id", "access_hash", "type", "phone_number", "last_update_on"}
        if version != (4,) or "update_state" not in tables or session_columns != expected_columns:
            raise RuntimeError("Unsupported legacy Telegram session schema; automatic conversion stopped")
        if peer_columns != expected_peers | ({"username"} if has_legacy_names else set()):
            raise RuntimeError("Unsupported legacy Telegram peer schema; automatic conversion stopped")
        if {row[1] for row in connection.execute("PRAGMA table_info(update_state)")} != {"id", "pts", "qts", "date", "seq"}:
            raise RuntimeError("Unsupported legacy Telegram update schema; automatic conversion stopped")
        if "usernames" in tables and {row[1] for row in connection.execute("PRAGMA table_info(usernames)")} != {"id", "username"}:
            raise SessionSchemaError(row[1] for row in connection.execute("PRAGMA table_info(usernames)"))

        backup_path = path.with_name(f"{path.name}.pyrofork-v4.{uuid4().hex}.bak")
        backup = sqlite3.connect(backup_path)
        try:
            connection.backup(backup)
        finally:
            backup.close()

        with connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("CREATE TABLE IF NOT EXISTS usernames (id INTEGER, username TEXT, FOREIGN KEY (id) REFERENCES peers(id))")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_usernames_id ON usernames (id)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_usernames_username ON usernames (username)")
            if has_legacy_names:
                connection.execute(
                    "INSERT INTO usernames (id, username) SELECT p.id, p.username FROM peers p "
                    "WHERE p.username IS NOT NULL AND NOT EXISTS "
                    "(SELECT 1 FROM usernames u WHERE u.id = p.id AND u.username = p.username)")
            connection.execute("UPDATE version SET number = 6")
        return True


def migrate_legacy_sessions(directory: Path = DEFAULT_SESSION_DIRECTORY) -> int:
    migrated = sum(migrate_legacy_session(path) for path in sorted(directory.glob("*.session")))
    if migrated:
        print(f"Migrated {migrated} legacy Telegram sessions; original backups are beside the session files", flush=True)
    return migrated


if __name__ == "__main__":
    migrate_legacy_sessions()
