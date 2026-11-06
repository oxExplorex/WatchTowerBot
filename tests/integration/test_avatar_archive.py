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
async def test_changed_photo_invalidates_old_download_lease(db_main):
    await PersonalKeyRepository(db_main.get_session_factory).install(123, create_key_bundle(123, "АватарАрхива123"))
    repository = AvatarsRepository(db_main.get_session_factory)
    def peer(photo_id):
        return SimpleNamespace(id=789, photo=SimpleNamespace(small_file_id=photo_id, small_photo_unique_id=photo_id))
    await repository.observe(123, 456, [peer("first")])
    item = await repository.claim()
    await repository.observe(123, 456, [peer("second")])
    await repository.finish(item, blob_key="a" * 64)
    async with db_main.get_session_factory()() as session:
        current = await session.scalar(select(ChatAvatar))
    assert current.blob_key is None and current.status == "pending"
    assert current.lease_token is None


@pytest.mark.asyncio
async def test_avatar_schema_upgrade_matches_model(db_main):
    from importlib import import_module
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    migration = import_module("migrations.versions.20261106_02_chat_avatars")
    async with db_main.get_session_factory()() as session:
        engine = session.bind
    def check(connection):
        ChatAvatar.__table__.drop(connection)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        columns = {column["name"] for column in sa.inspect(connection).get_columns("chat_avatar")}
        assert columns == set(ChatAvatar.model_fields)
        connection.execute(ChatAvatar.__table__.insert().values(owner_id=123, account_user_id=456,
            user_id=789, photo_key="synthetic"))
    async with engine.begin() as connection:
        await connection.run_sync(check)
