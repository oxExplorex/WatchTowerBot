"""Offline subprocess used to verify committed data survives an abrupt exit."""
import asyncio
import json
import logging
import os
from pathlib import Path
import sys
import types


async def probe(phase, root, port, database, media_root, marker):
    assert database.startswith("wt_test_") and len(database) == 40
    assert port > 1024 and port != 5432
    sys.path.insert(0, str(root))
    os.environ.update(BOT_DB_ENGINE="postgresql+asyncpg", BOT_DB_HOST="127.0.0.1", BOT_DB_PORT=str(port),
                      BOT_DB_USER="watchtower_test", BOT_DB_PASSWORD="", BOT_DB_NAME=database,
                      BOT_DB_ADMIN_NAME="postgres", DB_ENCRYPTION_KEY="test-encryption-key")
    config = types.ModuleType("data.config")
    config.admin_id_list = [123]
    sys.modules["data.config"] = config
    logger = types.ModuleType("core.logging")
    logger.bot_logger = logging.getLogger("release_probe")
    sys.modules["core.logging"] = logger

    from sqlalchemy import event, select
    from sqlalchemy.orm import Session
    from core.media_store import MediaStore
    from core.personal_crypto import create_key_bundle, unlock_private_key
    import db.main as db
    from db.media_models import MessageAttachment
    from db.message_models import MessageRevision, StoredMessage
    from db.repositories.media_repo import MediaRepository
    from db.repositories.personal_repo import PersonalKeyRepository
    from services.media_archive import archive_attachment
    from services.personal_archive import migrate_batch

    await db.connect_database()
    store = MediaStore(media_root)
    keys = PersonalKeyRepository(db.get_session_factory)
    data = b"release-private-file"

    async def record(identity, owner_id=123, with_media=False):
        return await db.messages_repository.record(owner_id=owner_id, account_user_id=456, chat_id=789,
            message_id=identity, source="business", event_key=f"release-update:{identity}", kind="new", sent_at=100,
            payload={"text": f"private-message-{identity}", "media": [{"kind": "document", "file_id": "offline-file",
                     "file_unique_id": "release-file", "file_size": len(data)}] if with_media else []})

    try:
        if phase == "seed":
            for identity in range(10, 16):
                await record(identity, with_media=identity == 10)
            await record(10, owner_id=999)

            async def download(file_id, *, destination, **kwargs):
                assert file_id == "offline-file"
                destination.write(data)

            media = MediaRepository(db.get_session_factory)
            await archive_attachment(types.SimpleNamespace(download=download), media, store, await media.claim())
            print(json.dumps({"seeded": 7}), flush=True)
            return
        if phase == "abort":
            bundle = create_key_bundle(123, "Сильный секрет 592")
            assert await keys.install(123, bundle)

            def abort_before_commit(session):
                # PostgreSQL has uncommitted new envelopes while the immutable
                # media file is already replaced. No Python finally can run.
                blobs = list(media_root.glob("123/*/*.wtm"))
                assert len(blobs) == 1 and blobs[0].read_bytes()[:4] == b"WTM2"
                with marker.open("wb") as stream:
                    stream.write(b"interrupted-before-database-commit")
                    stream.flush()
                    os.fsync(stream.fileno())
                os._exit(23)

            event.listen(Session, "before_commit", abort_before_commit)
            await migrate_batch(db.get_session_factory, 123, store, batch_size=2)
            raise AssertionError("Crash injection was not reached")
        assert phase in {"resume", "verify"}
        # This process has no private key in memory while writing and migrating.
        await record(99)
        for _ in range(100):
            if await migrate_batch(db.get_session_factory, 123, store, batch_size=2):
                break
        else:
            raise AssertionError("Migration did not complete")
        key = await keys.get(123)
        private = unlock_private_key(123, key, "Сильный секрет 592")
        async with db.get_session_factory()() as session:
            revisions = list((await session.scalars(select(MessageRevision).join(StoredMessage).where(StoredMessage.owner_id == 123))).all())
            other = list((await session.scalars(select(MessageRevision).join(StoredMessage).where(StoredMessage.owner_id == 999))).all())
            attachment = (await session.scalars(select(MessageAttachment))).one()
        assert len(revisions) == 7 and all(row.encryption_version == 2 for row in revisions)
        assert {db.messages_repository.decode_payload(row, owner_id=123, private_key=private)["text"] for row in revisions} == {
            f"private-message-{identity}" for identity in [10, 11, 12, 13, 14, 15, 99]}
        assert len(other) == 1 and other[0].encryption_version == 1
        assert store.read(123, attachment.blob_key, private_key=private) == data
        assert key.migration_state == "complete" and key.migrated_revisions == 6
        print(json.dumps({"personal_revisions": 7, "other_owner_legacy": 1, "state": key.migration_state,
                          "migrated": key.migrated_revisions, "files": key.migrated_files}), flush=True)
    finally:
        await db.close_database()


if __name__ == "__main__":
    phase, root, port, database, media_root, marker = sys.argv[1:]
    asyncio.run(probe(phase, Path(root).resolve(), int(port), database, Path(media_root), Path(marker)))
