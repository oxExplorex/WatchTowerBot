import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from core.backup_format import InvalidBackup
from core.media_store import MediaStore
from core.personal_crypto import create_key_bundle, unlock_private_key
from db.media_models import MessageAttachment
from db.message_models import StoredMessage, MessageRevision, MessageReceipt
from db.personal_models import OwnerArchiveKey
from db.repositories.personal_repo import PersonalKeyRepository
from db.repositories.media_repo import MediaRepository
from services.backup_snapshot import create_backup
from services.backup_restore import prepare_backup, restore_backup


@pytest.mark.asyncio
async def test_backup_restores_without_original_media_key_and_is_additive(db_main, tmp_path, monkeypatch):
    owner, secret = 123, "СекретАрхива123"
    bundle = create_key_bundle(owner, secret)
    await PersonalKeyRepository(db_main.get_session_factory).install(owner, bundle)
    for identity, text in ((1, "секретный текст"), (2, "другая редакция")):
        await db_main.messages_repository.record(owner_id=owner, account_user_id=456, chat_id=789,
            message_id=10, kind="new" if identity == 1 else "edit", source="business", event_key=str(identity),
            version_at=identity, payload={"text": text, "media": [{"kind": "document", "file_id": "file",
                "file_unique_id": "unique", "file_size": 7}]})
    await db_main.messages_repository.record(owner_id=999, account_user_id=888, chat_id=777,
        message_id=1, kind="new", source="business", event_key="other", payload={"text": "foreign", "media": []})
    await db_main.messages_repository.record(owner_id=owner, account_user_id=456, chat_id=789,
        message_id=10, kind="delete", source="business", event_key="deleted")
    store = MediaStore(tmp_path / "old-media")
    with store.writer(owner, public_key=bundle["public_key"]) as writer:
        writer.write(b"private")
        blob_key, size = writer.finish()
    media = MediaRepository(db_main.get_session_factory)
    for _ in range(2):
        item = await media.claim()
        await media.finish(item, blob_key=blob_key, stored_size=size, encryption_version=2)
    paths, counts = await create_backup(owner, tmp_path / "export", uuid4().hex,
        session_factory=db_main.get_session_factory, store=store)
    assert counts["messages"] == 1 and counts["revisions"] == 2 and counts["media"] == 1
    assert "секретный текст".encode() not in b"".join(p.read_bytes() for p in paths)
    with pytest.raises(InvalidBackup):
        prepare_backup(paths, tmp_path / "bad-secret", owner, "НеверныйСекрет123")
    with pytest.raises(InvalidBackup):
        prepare_backup(paths, tmp_path / "bad-owner", 999, secret)
    async with db_main.create_unit_of_work() as uow:
        revision_ids = select(MessageRevision.uuid).join(StoredMessage).where(StoredMessage.owner_id == owner)
        await uow.session.execute(delete(MessageAttachment).where(MessageAttachment.owner_id == owner))
        await uow.session.execute(delete(MessageReceipt).where(MessageReceipt.message_uuid.in_(
            select(StoredMessage.uuid).where(StoredMessage.owner_id == owner))))
        await uow.session.execute(delete(MessageRevision).where(MessageRevision.uuid.in_(revision_ids)))
        await uow.session.execute(delete(StoredMessage).where(StoredMessage.owner_id == owner))
        await uow.session.execute(delete(OwnerArchiveKey).where(OwnerArchiveKey.owner_id == owner))
        await uow.commit()
    import core.media_store as media_module
    monkeypatch.setattr(media_module, "media_encryption_key", lambda owner: hashlib.sha256(b"new server key").digest())
    target = MediaStore(tmp_path / "new-media")
    prepared = prepare_backup(paths, tmp_path / "prepared", owner, secret)
    result = await restore_backup(prepared, owner, secret, session_factory=db_main.get_session_factory, store=target)
    assert result == {"messages": 1, "revisions": 2, "attachments": 2}
    async with db_main.create_unit_of_work() as uow:
        attachments = list(await uow.session.scalars(select(MessageAttachment).where(MessageAttachment.owner_id == owner)))
        assert all(target.read(owner, item.blob_key, private_key=unlock_private_key(owner, bundle, secret)) == b"private"
                   for item in attachments)
        rows = list(await uow.session.scalars(select(StoredMessage).where(StoredMessage.owner_id == owner)))
        assert len(rows) == 1 and rows[0].is_edited and rows[0].is_deleted
    replay = prepare_backup(paths, tmp_path / "replay", owner, secret)
    assert await restore_backup(replay, owner, secret, session_factory=db_main.get_session_factory, store=target) == {
        "messages": 0, "revisions": 0, "attachments": 0}
    corrupt = tmp_path / "truncated.wtb"
    corrupt.write_bytes(paths[0].read_bytes()[:-1])
    with pytest.raises(InvalidBackup):
        prepare_backup([corrupt], tmp_path / "truncated", owner, secret)
