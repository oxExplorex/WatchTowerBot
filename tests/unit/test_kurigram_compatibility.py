from importlib import metadata
from contextlib import closing
import sqlite3

import pytest

from pyrogram import Client, compose, filters
from pyrogram.errors import FloodWait, InternalServerError, PhoneCodeExpired, RPCError, SessionPasswordNeeded
from pyrogram.handlers import MessageHandler
from pyrogram.types import Chat, Message, User
from pyrogram.storage import SQLiteStorage

from scripts.install_dependencies import KURIGRAM_VERSION
from scripts.migrate_telegram_sessions import migrate_legacy_sessions
from scripts import migrate_telegram_sessions as session_migration


def test_installed_distribution_matches_reviewed_release():
    assert metadata.version("Kurigram") == KURIGRAM_VERSION


def test_required_client_api_is_available_without_connecting():
    for method in (
        "connect", "disconnect", "start", "stop", "send_phone_number_code",
        "sign_in", "check_password", "get_dialogs", "get_dialogs_count",
        "get_me", "download_media", "add_handler",
    ):
        assert callable(getattr(Client, method))
    assert callable(compose)
    assert callable(MessageHandler)
    assert filters.text is not None
    assert all(issubclass(error, RPCError) for error in (
        FloodWait, InternalServerError, PhoneCodeExpired, SessionPasswordNeeded,
    ))


def test_required_message_and_name_api_is_available():
    assert callable(Message.download)
    assert callable(Message.edit_text)
    assert Chat(id=1, first_name="Test", last_name="User").full_name == "Test User"
    assert User(id=1, first_name="Test", last_name="User").full_name == "Test User"


@pytest.fixture
def legacy_session(tmp_path):
    path = tmp_path / "legacy.session"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(
            "CREATE TABLE sessions (dc_id INTEGER PRIMARY KEY, api_id INTEGER, test_mode INTEGER, "
            "auth_key BLOB, date INTEGER NOT NULL, user_id INTEGER, is_bot INTEGER);"
            "CREATE TABLE peers (id INTEGER PRIMARY KEY, access_hash INTEGER, type TEXT NOT NULL, "
            "username TEXT, phone_number TEXT, last_update_on INTEGER);"
            "CREATE TABLE update_state (id INTEGER PRIMARY KEY, pts INTEGER, qts INTEGER, date INTEGER, seq INTEGER);"
            "CREATE TABLE version (number INTEGER PRIMARY KEY);"
            "INSERT INTO version VALUES (4);"
            "INSERT INTO peers VALUES (11, 22, 'user', 'legacy_user', NULL, 1700000000);"
            "INSERT INTO update_state VALUES (0, 1, 2, 1700000000, 3);"
        )
        connection.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?)",
            (2, 12345, 0, bytes(range(256)), 1700000000, 123456, 0),
        )
    return path


@pytest.mark.asyncio
async def test_direct_pyrofork_session_open_is_incompatible(legacy_session):
    storage = SQLiteStorage("legacy", legacy_session.parent)
    try:
        with pytest.raises(sqlite3.OperationalError, match="update_state already exists"):
            await storage.open()
    finally:
        await storage.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_names", [True, False])
async def test_bridge_recovers_a_partly_migrated_session_with_existing_usernames(legacy_session, legacy_names):
    with closing(sqlite3.connect(legacy_session)) as connection, connection:
        connection.execute("CREATE TABLE usernames (id INTEGER, username TEXT)")
        connection.execute("INSERT INTO usernames VALUES (11, 'already_cached')")
        if not legacy_names:
            connection.execute("ALTER TABLE peers DROP COLUMN username")
    storage = SQLiteStorage("legacy", legacy_session.parent)
    try:
        with pytest.raises(sqlite3.OperationalError, match="update_state already exists"):
            await storage.open()
    finally:
        await storage.close()
    assert migrate_legacy_sessions(legacy_session.parent) == 1
    backups = list(legacy_session.parent.glob("*.pyrofork-v4.*.bak"))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as backup:
        assert backup.execute("SELECT number FROM version").fetchone() == (4,)
        assert backup.execute("SELECT id, username FROM usernames").fetchall() == [(11, "already_cached")]
    storage = SQLiteStorage("legacy", legacy_session.parent)
    try:
        await storage.open()
        assert await storage.version() == 7
        assert await storage.auth_key() == bytes(range(256))
        assert storage.conn.execute("SELECT id, username FROM usernames ORDER BY username").fetchall() == (
            [(11, "already_cached"), (11, "legacy_user")] if legacy_names else [(11, "already_cached")])
        assert storage.conn.execute("SELECT pts, qts, seq FROM update_state").fetchone() == (1, 2, 3)
    finally:
        await storage.close()
    assert migrate_legacy_sessions(legacy_session.parent) == 0
    assert list(legacy_session.parent.glob("*.pyrofork-v4.*.bak")) == backups


def test_partial_session_with_unknown_username_schema_is_not_changed(legacy_session):
    with closing(sqlite3.connect(legacy_session)) as connection, connection:
        connection.execute("CREATE TABLE usernames (unknown TEXT)")
    before = legacy_session.read_bytes()
    with pytest.raises(RuntimeError, match="Unsupported legacy Telegram username"):
        migrate_legacy_sessions(legacy_session.parent)
    assert legacy_session.read_bytes() == before
    assert not list(legacy_session.parent.glob("*.bak"))


@pytest.mark.asyncio
@pytest.mark.parametrize("version", [4, 5, 6])
async def test_native_session_uses_kurigram_upgrade_unchanged(legacy_session, version):
    with closing(sqlite3.connect(legacy_session)) as connection, connection:
        connection.execute("ALTER TABLE peers DROP COLUMN username")
        if version == 4:
            connection.execute("DROP TABLE update_state")
        connection.execute("CREATE TABLE usernames (id INTEGER, username TEXT)")
        connection.execute("UPDATE version SET number = ?", (version,))
        if version == 6:
            connection.execute("CREATE INDEX idx_usernames_id ON usernames (id)")
    before = legacy_session.read_bytes()
    assert migrate_legacy_sessions(legacy_session.parent) == 0
    assert legacy_session.read_bytes() == before
    storage = SQLiteStorage("legacy", legacy_session.parent)
    try:
        await storage.open()
        assert await storage.version() == 7
        assert await storage.auth_key() == bytes(range(256))
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_legacy_session_bridge_preserves_authorization_and_peers(legacy_session):
    assert migrate_legacy_sessions(legacy_session.parent) == 1
    backups = list(legacy_session.parent.glob("*.pyrofork-v4.*.bak"))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as backup:
        assert backup.execute("SELECT number FROM version").fetchone() == (4,)
        assert backup.execute("SELECT auth_key FROM sessions").fetchone() == (bytes(range(256)),)

    storage = SQLiteStorage("legacy", legacy_session.parent)
    try:
        await storage.open()
        assert await storage.version() == 7
        assert await storage.auth_key() == bytes(range(256))
        assert await storage.user_id() == 123456
        assert await storage.server_address() == "149.154.167.51"
        assert storage.conn.execute("SELECT id, username FROM usernames").fetchall() == [(11, "legacy_user")]
        assert storage.conn.execute("SELECT pts, qts, seq FROM update_state").fetchone() == (1, 2, 3)
    finally:
        await storage.close()
    assert migrate_legacy_sessions(legacy_session.parent) == 0
    assert list(legacy_session.parent.glob("*.pyrofork-v4.*.bak")) == backups


def test_unknown_legacy_schema_is_not_modified(legacy_session):
    with closing(sqlite3.connect(legacy_session)) as connection, connection:
        connection.execute("UPDATE version SET number = 3")
    with pytest.raises(RuntimeError, match="Unsupported legacy"):
        migrate_legacy_sessions(legacy_session.parent)
    assert list(legacy_session.parent.glob("*.bak")) == []
    with closing(sqlite3.connect(legacy_session)) as connection:
        assert connection.execute("SELECT number FROM version").fetchone() == (3,)


@pytest.mark.parametrize("existing_names", [False, True])
def test_failed_session_conversion_rolls_back_and_keeps_backup(monkeypatch, legacy_session, existing_names):
    if existing_names:
        with closing(sqlite3.connect(legacy_session)) as connection, connection:
            connection.execute("CREATE TABLE usernames (id INTEGER, username TEXT)")
            connection.execute("INSERT INTO usernames VALUES (11, 'already_cached')")
    original_connect = sqlite3.connect

    class FailingConnection(sqlite3.Connection):
        def execute(self, statement, parameters=()):
            if statement == "UPDATE version SET number = 6":
                raise sqlite3.OperationalError("simulated write failure")
            return super().execute(statement, parameters)

    def failing_connect(*arguments, **options):
        return original_connect(*arguments, factory=FailingConnection, **options)

    with monkeypatch.context() as scoped_patch:
        scoped_patch.setattr(session_migration.sqlite3, "connect", failing_connect)
        with pytest.raises(sqlite3.OperationalError, match="simulated"):
            migrate_legacy_sessions(legacy_session.parent)

    assert len(list(legacy_session.parent.glob("*.pyrofork-v4.*.bak"))) == 1
    with closing(sqlite3.connect(legacy_session)) as connection:
        assert connection.execute("SELECT number FROM version").fetchone() == (4,)
        if existing_names:
            assert connection.execute("SELECT id, username FROM usernames").fetchall() == [(11, "already_cached")]
        else:
            assert connection.execute("SELECT name FROM sqlite_master WHERE name = 'usernames'").fetchone() is None
        assert connection.execute("SELECT auth_key FROM sessions").fetchone() == (bytes(range(256)),)
