from sqlalchemy import select
import pytest

from core.media_store import MediaStore
from db.avatar_models import ChatAvatar
from db.history_models import HistoryChat, HistoryRange
from db.media_models import MessageAttachment
from db.message_models import MessageRevision
from db.repositories.messages_repo import MessagesRepository
from services.archive_statistics import archive_statistics


@pytest.mark.asyncio
async def test_persisted_archive_totals_include_coverage_and_unique_actual_file_sizes(db_main, tmp_path):
    await db_main.create_app_tg(123, 12345, "synthetic", "app")
    app = (await db_main.get_app_tg_user_id(123))[0][0]
    await db_main.create_account_tg(123, 456, app.uuid, "79000000001")
    account = (await db_main.get_accounts_for_user_id(456))[0]
    await db_main.create_dump_chat_user(456, 790)
    for event, content in (("new", "original"), ("edit", "edited")):
        await db_main.messages_repository.record(owner_id=123, account_user_id=456, chat_id=789, message_id=1,
            source="business", kind=event, event_key=event, payload={"text": content, "media": [
                {"kind": "document", "file_id": "same", "file_unique_id": "same"}]})
    await db_main.messages_repository.record(owner_id=123, account_user_id=456, chat_id=791, message_id=2,
        source="userbot", kind="new", event_key="missing", payload={"text": "other", "media": [
            {"kind": "document", "file_id": "missing", "file_unique_id": "missing"}]})
    await db_main.messages_repository.record(owner_id=124, account_user_id=457, chat_id=999, message_id=1,
        source="business", kind="new", event_key="foreign", payload={"text": "foreign", "media": []})
    store = MediaStore(tmp_path / "media")
    with store.writer(123, compress="auto") as writer:
        writer.write(b"a" * 10000)
        blob, _ = writer.finish()
    actual_size = store.path(123, blob).stat().st_size
    async with db_main.get_session_factory()() as session, session.begin():
        for item in await session.scalars(select(MessageAttachment).where(MessageAttachment.owner_id == 123)):
            revision = await session.get(MessageRevision, item.revision_uuid)
            file_id = db_main.messages_repository.decode_payload(revision)["media"][0]["file_id"]
            item.blob_key = "f" * 64 if file_id == "missing" else blob
            item.status = "stored"
        session.add(ChatAvatar(owner_id=123, account_user_id=456, user_id=789, photo_key="shared",
                               status="stored", blob_key=blob))
        session.add_all([HistoryChat(account_uuid=account.uuid, chat_id=789),
                         HistoryChat(account_uuid=account.uuid, chat_id=790, reached_start=True),
                         HistoryChat(account_uuid=account.uuid, chat_id=792, excluded=True),
                         HistoryRange(account_uuid=account.uuid, chat_id=789, low_id=1, high_id=100)])
    stats = await archive_statistics(MessagesRepository(db_main.get_session_factory), 123, store=store)
    assert (stats["messages"], stats["revisions"], stats["chats"], stats["chats_with_messages"]) == (2, 3, 3, 2)
    assert (stats["history_chats"], stats["history_checked"], stats["history_reached"]) == (2, 2, 1)
    assert stats["attachments"] == stats["media_stored"] == 3
    assert stats["media_files"] == 2 and stats["media_unavailable"] == 1
    assert stats["media_bytes"] == actual_size < 10000
    assert stats["content_bytes"] > 0 and stats["archive_bytes"] == stats["content_bytes"] + actual_size
    assert await archive_statistics(MessagesRepository(db_main.get_session_factory), 123, store=store) == stats
