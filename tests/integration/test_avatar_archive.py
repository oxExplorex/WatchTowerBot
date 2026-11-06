from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from archive_viewer.archive import Archive
from core.media_store import MediaStore
from core.personal_crypto import create_key_bundle, unlock_private_key
from db.avatar_models import ChatAvatar
from db.repositories.avatars_repo import AvatarsRepository
from db.repositories.media_repo import MediaRepository
from db.repositories.personal_repo import PersonalKeyRepository
from services.backup_snapshot import create_backup
from services.backup_restore import prepare_backup, restore_backup


@pytest.mark.asyncio
async def test_avatar_is_encrypted_owner_scoped_exported_and_restored(db_main, tmp_path, offline_module):
    archive_avatar = offline_module("services/avatar_archive.py").archive_avatar
    owner, account_id, peer = 123, 456, 789
    secret = "АватарАрхива123"
    bundle = create_key_bundle(owner, secret)
    await PersonalKeyRepository(db_main.get_session_factory).install(owner, bundle)
    await db_main.messages_repository.record(owner_id=owner, account_user_id=account_id, chat_id=peer,
        message_id=1, kind="new", source="business", event_key="one", sent_at=100,
        payload={"text": "private", "media": []})
    repository = AvatarsRepository(db_main.get_session_factory)
    contact = SimpleNamespace(id=peer, photo=SimpleNamespace(small_file_id="synthetic-avatar-id",
        small_photo_unique_id="synthetic-avatar-unique"))
    await repository.observe(owner, account_id, [contact])
    item = await repository.claim()
    assert item.file_id != "synthetic-avatar-id"
    data = b"\x89PNG\r\n\x1a\nsynthetic-image"
    async def stream(file_id):
        assert file_id == "synthetic-avatar-id"
        yield data
    client = SimpleNamespace(stream_media=stream)
    store = MediaStore(tmp_path / "media")
    limits = SimpleNamespace(media_slot=AsyncMock(return_value=0), defer=AsyncMock())
    await archive_avatar(SimpleNamespace(), repository, store, item, limits=limits,
        keys=MediaRepository(db_main.get_session_factory), resolve_client=AsyncMock(return_value=client),
        run_client=lambda client, operation: operation())
    async with db_main.get_session_factory()() as session:
        saved = await session.scalar(select(ChatAvatar))
    assert saved.status == "stored" and saved.file_id is None
    assert store.version(owner, saved.blob_key) == 2
    assert data not in store.path(owner, saved.blob_key).read_bytes()
    with pytest.raises(PermissionError):
        store.read(owner, saved.blob_key)
    assert store.read(owner, saved.blob_key, private_key=unlock_private_key(owner, bundle, secret)) == data
    await repository.observe(owner, account_id, [contact])
    assert await repository.claim() is None
    paths, counts = await create_backup(owner, tmp_path / "parts", uuid4().hex,
        session_factory=db_main.get_session_factory, store=store)
    assert counts["avatars"] == 1 and counts["media"] == 0
    viewer = Archive.open(paths[0], secret)
    try:
        assert viewer.chat_list()[0]["avatar"] == "456:789"
        assert viewer.avatar("456:789") == data
        import threading
        from urllib.request import build_opener, ProxyHandler, Request
        from archive_viewer.server import ViewerServer
        with ViewerServer(paths[0]) as server:
            server.archive = viewer
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                request = Request(server.origin + "/api/avatar/456%3A789", headers={"X-Viewer-Token": server.token})
                with build_opener(ProxyHandler({})).open(request, timeout=5) as response:
                    assert response.headers["Content-Type"] == "image/png" and response.read() == data
            finally:
                server.shutdown()
                thread.join(timeout=5)
    finally:
        viewer.close()
    foreign, _ = await create_backup(owner, tmp_path / "foreign", uuid4().hex,
        account_user_id=account_id, chat_id=999,
        session_factory=db_main.get_session_factory, store=store)
    viewer = Archive.open(foreign[0], secret)
    try:
        assert not viewer.avatars
    finally:
        viewer.close()
    prepared = prepare_backup(paths, tmp_path / "restore", owner, secret)
    async with db_main.get_session_factory()() as session, session.begin():
        await session.execute(delete(ChatAvatar))
    restored_store = MediaStore(tmp_path / "restored-media")
    await restore_backup(prepared, owner, secret, session_factory=db_main.get_session_factory, store=restored_store)
    async with db_main.get_session_factory()() as session:
        restored = await session.scalar(select(ChatAvatar))
    assert restored_store.read(owner, restored.blob_key, private_key=unlock_private_key(owner, bundle, secret)) == data


@pytest.mark.asyncio
async def test_changed_photo_retains_previous_download_and_its_lease(db_main):
    await PersonalKeyRepository(db_main.get_session_factory).install(123, create_key_bundle(123, "АватарАрхива123"))
    repository = AvatarsRepository(db_main.get_session_factory)
    def peer(photo_id):
        return SimpleNamespace(id=789, photo=SimpleNamespace(small_file_id=photo_id, small_photo_unique_id=photo_id))
    await repository.observe(123, 456, [peer("first")])
    item = await repository.claim()
    await repository.observe(123, 456, [peer("second")])
    await repository.finish(item, blob_key="a" * 64)
    async with db_main.get_session_factory()() as session:
        current = await session.scalar(select(ChatAvatar).where(ChatAvatar.ended_at.is_(None)))
        previous = await session.get(ChatAvatar, item.uuid)
    assert current.blob_key is None and current.status == "pending"
    assert current.lease_token is None
    assert previous.blob_key == "a" * 64 and previous.status == "stored" and previous.ended_at is not None


@pytest.mark.asyncio
async def test_avatar_schema_upgrade_matches_model(db_main):
    from importlib import import_module
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    migration = import_module("migrations.versions.20261106_02_chat_avatars")
    history_migration = import_module("migrations.versions.20261106_03_avatar_history")
    async with db_main.get_session_factory()() as session:
        engine = session.bind
    def check(connection):
        ChatAvatar.__table__.drop(connection)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            old = sa.Table("chat_avatar", sa.MetaData(), autoload_with=connection)
            identity = uuid4()
            connection.execute(old.insert().values(uuid=identity.hex if connection.dialect.name == "sqlite" else identity,
                owner_id=123, account_user_id=456,
                user_id=999, photo_key="old", source="userbot", status="stored", next_attempt_at=0,
                lease_until=0, state_version=0, updated_at=100))
            history_migration.upgrade()
        columns = {column["name"] for column in sa.inspect(connection).get_columns("chat_avatar")}
        assert columns == set(ChatAvatar.model_fields)
        assert connection.scalar(sa.select(ChatAvatar.first_seen_at).where(ChatAvatar.user_id == 999)) == 100_000_000
        connection.execute(ChatAvatar.__table__.insert().values(owner_id=123, account_user_id=456,
            user_id=789, photo_key="synthetic"))
    async with engine.begin() as connection:
        await connection.run_sync(check)


@pytest.mark.asyncio
async def test_avatar_removal_reappearance_and_backup_keep_every_occurrence(db_main, tmp_path):
    owner, account, peer, secret = 123, 456, 789, "АватарАрхива123"
    bundle = create_key_bundle(owner, secret)
    await PersonalKeyRepository(db_main.get_session_factory).install(owner, bundle)
    await db_main.messages_repository.record(owner_id=owner, account_user_id=account, chat_id=peer,
        message_id=1, kind="new", source="userbot", event_key="one", payload={"text": "private", "media": []})
    repository, store = AvatarsRepository(db_main.get_session_factory), MediaStore(tmp_path / "media")
    contact = SimpleNamespace(id=peer, photo=SimpleNamespace(small_file_id="photo", small_photo_unique_id="same"))
    await repository.observe(owner, account, [contact], authoritative=True)
    item = await repository.claim()
    with store.writer(owner, public_key=bundle["public_key"]) as writer:
        writer.write(b"\x89PNG\r\n\x1a\nsynthetic-avatar")
        blob, _ = writer.finish()
    await repository.finish(item, blob_key=blob)
    # A minimal message without a photo must not erase an observed profile picture.
    empty = SimpleNamespace(id=peer, photo=None)
    await repository.observe(owner, account, [empty])
    async with db_main.get_session_factory()() as session:
        assert len(list(await session.scalars(select(ChatAvatar)))) == 1
    await repository.observe(owner, account, [empty], authoritative=True)
    paths, _ = await create_backup(owner, tmp_path / "no-avatar", uuid4().hex,
        session_factory=db_main.get_session_factory, store=store)
    viewer = Archive.open(paths[0], secret)
    try:
        assert viewer.chat_list()[0]["avatar"] is None
        assert any(item["available"] for item in viewer.avatar_entries("456:789"))
    finally:
        viewer.close()
    await repository.observe(owner, account, [contact], authoritative=True)
    async with db_main.get_session_factory()() as session:
        saved = list(await session.scalars(select(ChatAvatar)))
    assert len(saved) == 3 and sum(item.ended_at is None for item in saved) == 1
    assert len([item for item in saved if item.blob_key == blob]) == 2  # Same bytes, separate occurrences.
    paths, counts = await create_backup(owner, tmp_path / "returned", uuid4().hex,
        session_factory=db_main.get_session_factory, store=store)
    assert counts["avatars"] == 2
    prepared = prepare_backup(paths, tmp_path / "import", owner, secret)
    async with db_main.get_session_factory()() as session, session.begin():
        await session.execute(delete(ChatAvatar))
    await restore_backup(prepared, owner, secret, session_factory=db_main.get_session_factory, store=store)
    await restore_backup(prepared, owner, secret, session_factory=db_main.get_session_factory, store=store)
    async with db_main.get_session_factory()() as session:
        assert len(list(await session.scalars(select(ChatAvatar)))) == 3


@pytest.mark.asyncio
async def test_history_refresh_downloads_only_current_owners_avatar(db_main, tmp_path, offline_module, monkeypatch):
    module = offline_module("services/avatar_archive.py")
    monkeypatch.setattr(module, "get_session_factory", db_main.get_session_factory)
    for owner in (123, 999):
        await PersonalKeyRepository(db_main.get_session_factory).install(owner, create_key_bundle(owner, "АватарАрхива123"))
    await db_main.create_app_tg(123, 12345, "synthetic", "app")
    app = (await db_main.get_app_tg_user_id(123))[0][0]
    await db_main.create_account_tg(123, 456, app.uuid, "79000000001")
    repository = AvatarsRepository(db_main.get_session_factory)
    def contact(file_id):
        return SimpleNamespace(id=789, photo=SimpleNamespace(small_file_id=file_id, small_photo_unique_id=file_id))
    await repository.observe(999, 456, [contact("old-owner")])
    downloaded = []
    async def stream(file_id):
        downloaded.append(file_id)
        yield b"\x89PNG\r\n\x1a\nsynthetic-avatar"
    client = SimpleNamespace(get_chat=AsyncMock(return_value=contact("current-owner")), stream_media=stream)
    limits = SimpleNamespace(blocked_until=AsyncMock(return_value=0), media_slot=AsyncMock(return_value=0), defer=AsyncMock())
    await module.collect_chat_avatar(SimpleNamespace(), client, SimpleNamespace(user_id=456, admin_id=123), 789,
        repository=repository, store=MediaStore(tmp_path / "media"), limits=limits)
    assert downloaded == ["current-owner"]
    async with db_main.get_session_factory()() as session:
        rows = {row.owner_id: row.status for row in await session.scalars(select(ChatAvatar))}
    assert rows == {123: "stored", 999: "pending"}
