import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, update

from core.media_store import MediaStore
from core.personal_crypto import context, create_key_bundle, open_text, unlock_private_key
from db.media_models import MessageAttachment
from db.message_models import MessageRevision, StoredMessage
from db.personal_models import OwnerArchiveKey
from db.repositories.media_repo import MediaRepository
from db.repositories.personal_repo import PersonalKeyRepository
from services.personal_archive import migrate_batch
from utils.crypto_store import DecryptionError, decrypt_text


@pytest.fixture(scope="module")
def bundle():
    return create_key_bundle(123, "Личный секрет 592")


async def ingest(db, message_id=10, *, owner_id=123, media=False):
    return await db.messages_repository.record(owner_id=owner_id, account_user_id=456, chat_id=789,
        message_id=message_id, source="business", event_key=f"update:{message_id}", kind="new", sent_at=100,
        payload={"text": f"Private {message_id}", "media": [{"kind": "document", "file_id": "offline-file",
                  "file_unique_id": "shared", "file_size": 12}] if media else []})


async def rows(db, model):
    async with db.get_session_factory()() as session:
        return list((await session.scalars(select(model))).all())


@pytest.mark.asyncio
async def test_setup_racing_ingestion_restart_and_owner_isolation(db_main, bundle, tmp_path):
    repository = PersonalKeyRepository(db_main.get_session_factory)
    for number in range(10, 16):
        await ingest(db_main, number)
    await ingest(db_main, owner_id=999)
    await asyncio.gather(repository.install(123, bundle), *[ingest(db_main, number) for number in range(16, 21)])
    assert not await repository.install(123, bundle)
    # A new repository models a restart; migration needs only the public key.
    store = MediaStore(tmp_path / "media")
    assert not await migrate_batch(db_main.get_session_factory, 123, store, batch_size=2)
    first = await repository.get(123)
    assert first.migrated_revisions == 2
    await ingest(db_main, 30)
    while not await migrate_batch(db_main.get_session_factory, 123, store, batch_size=2):
        pass
    assert await migrate_batch(db_main.get_session_factory, 123, store)
    revisions = await rows(db_main, MessageRevision)
    assert sum(row.encryption_version == 2 for row in revisions) == 12
    assert sum(row.encryption_version == 1 for row in revisions) == 1
    private = unlock_private_key(123, bundle, "Личныйсекрет592")
    for row in revisions:
        if row.encryption_version == 2:
            with pytest.raises(PermissionError):
                db_main.messages_repository.decode_payload(row)
            assert db_main.messages_repository.decode_payload(row, owner_id=123, private_key=private)["text"].startswith("Private")
    assert (await repository.get(123)).migration_state == "complete"
    assert 6 <= (await repository.get(123)).migrated_revisions <= 11


@pytest.mark.asyncio
async def test_corrupt_legacy_row_rolls_back_batch_without_destroying_ciphertext(db_main, bundle, tmp_path):
    await ingest(db_main)
    await ingest(db_main, 11)
    before = await rows(db_main, MessageRevision)
    corrupt = before[-1]
    async with db_main.get_session_factory()() as session, session.begin():
        await session.execute(update(MessageRevision).where(MessageRevision.uuid == corrupt.uuid).values(payload="enc:v1:broken"))
    await PersonalKeyRepository(db_main.get_session_factory).install(123, bundle)
    with pytest.raises(DecryptionError):
        await migrate_batch(db_main.get_session_factory, 123, MediaStore(tmp_path / "media"))
    after = {row.uuid: row for row in await rows(db_main, MessageRevision)}
    assert all(row.encryption_version == 1 for row in after.values())
    assert after[corrupt.uuid].payload == "enc:v1:broken"
    other = next(row for row in before if row.uuid != corrupt.uuid)
    assert after[other.uuid].payload == other.payload


@pytest.mark.asyncio
async def test_media_migration_crash_after_publish_and_new_download_dedup(db_main, bundle, tmp_path):
    from services.media_archive import archive_attachment

    await ingest(db_main, media=True)
    repository = MediaRepository(db_main.get_session_factory)
    store = MediaStore(tmp_path / "media")

    async def download(file_id, *, destination, **kwargs):
        destination.write(b"private-file")

    bot = SimpleNamespace(download=AsyncMock(side_effect=download))
    await archive_attachment(bot, repository, store, await repository.claim())
    item = (await rows(db_main, MessageAttachment))[0]
    await PersonalKeyRepository(db_main.get_session_factory).install(123, bundle)
    # Filesystem commit before DB commit: the next run must handle this state.
    store.migrate_blob(123, item.blob_key, bundle["public_key"])
    assert store.version(123, item.blob_key) == 2
    assert item.encryption_version == 1
    assert await migrate_batch(db_main.get_session_factory, 123, store)
    private = unlock_private_key(123, bundle, "Личный секрет 592")
    with pytest.raises(PermissionError):
        store.read(123, item.blob_key)
    assert store.read(123, item.blob_key, private_key=private) == b"private-file"
    migrated = (await rows(db_main, MessageAttachment))[0]
    assert migrated.sources_encryption_version == migrated.encryption_version == 2
    locators = json.loads(open_text(private, migrated.sources, context(123, f"sources:{item.uuid}")))
    assert locators[0]["file_id"] == "offline-file"
    await ingest(db_main, 11, media=True)
    await archive_attachment(bot, repository, store, await repository.claim())
    assert bot.download.await_count == 1
    assert all(row.encryption_version == 2 for row in await rows(db_main, MessageAttachment))
    assert len(list(tmp_path.rglob("*.wtm"))) == 1


@pytest.mark.asyncio
async def test_download_started_before_setup_reopens_completed_migration(db_main, bundle, tmp_path):
    from services.media_archive import archive_attachment

    await ingest(db_main, media=True)
    repository = MediaRepository(db_main.get_session_factory)
    store = MediaStore(tmp_path / "media")
    started, release = asyncio.Event(), asyncio.Event()

    async def download(file_id, *, destination, **kwargs):
        destination.write(b"private-file")
        started.set()
        await release.wait()

    task = asyncio.create_task(archive_attachment(SimpleNamespace(download=download), repository, store, await repository.claim()))
    await started.wait()
    keys = PersonalKeyRepository(db_main.get_session_factory)
    await keys.install(123, bundle)
    assert await migrate_batch(db_main.get_session_factory, 123, store)
    release.set()
    await task
    assert (await keys.get(123)).migration_state == "pending"
    assert await migrate_batch(db_main.get_session_factory, 123, store)
    item = (await rows(db_main, MessageAttachment))[0]
    assert store.version(123, item.blob_key) == 2


@pytest.mark.asyncio
async def test_deleting_account_and_app_keeps_archive_and_owner_key(db_main, bundle):
    from db.models import HistoryUser

    await db_main.create_app_tg(123, 555, "offline-api-hash", "offline")
    apps, _ = await db_main.get_app_tg_user_id(123)
    account = await db_main.create_account_tg(123, 456, apps[0].uuid, "79990000000")
    await PersonalKeyRepository(db_main.get_session_factory).install(123, bundle)
    await ingest(db_main, media=True)
    assert await db_main.del_account_uuid(account.uuid, 123)
    assert await db_main.del_app_tg_uuid(apps[0].uuid, 123)
    assert len(await rows(db_main, StoredMessage)) == len(await rows(db_main, MessageRevision)) == 1
    assert len(await rows(db_main, MessageAttachment)) == len(await rows(db_main, HistoryUser)) == 1
    assert (await rows(db_main, OwnerArchiveKey))[0].owner_id == 123


@pytest.mark.asyncio
async def test_orphan_blob_and_quota_full_archive_are_migrated_without_deletion(db_main, bundle, tmp_path):
    store = MediaStore(tmp_path / "media", max_total_bytes=1000)
    with store.writer(123) as writer:
        writer.write(b"orphan-secret")
        identity, _ = writer.finish()
    with store.writer(123) as writer:
        writer.write(b"another-orphan")
        second, _ = writer.finish()
    # Logical quota has no free space, but replacement credits the old version.
    store.max_total_bytes = sum(path.stat().st_size for path in tmp_path.rglob("*.wtm"))
    await PersonalKeyRepository(db_main.get_session_factory).install(123, bundle)
    assert not await migrate_batch(db_main.get_session_factory, 123, store)
    assert await migrate_batch(db_main.get_session_factory, 123, store)
    assert store.path(123, identity).exists()
    assert store.legacy_blob(123) is None
    assert store.read(123, identity, private_key=unlock_private_key(123, bundle, "Личный секрет 592")) == b"orphan-secret"
    assert store.version(123, second) == 2
