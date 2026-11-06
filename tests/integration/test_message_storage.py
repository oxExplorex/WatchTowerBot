import asyncio

import pytest
from sqlalchemy import func, select

from db.message_models import MessageReceipt, MessageRevision, PendingMessageDeletion, StoredMessage
from db.models import DumpChatUser, HistoryUser


def event(**changes):
    return dict(owner_id=123, account_user_id=456, chat_id=789, message_id=10,
                source="business", event_key="original", kind="new",
                sent_at=100, version_at=100, payload={"text": "Private", "media": []}) | changes


async def rows(db, model):
    async with db.create_unit_of_work() as uow:
        return list((await uow.session.scalars(select(model))).all())


@pytest.mark.asyncio
async def test_parallel_sources_share_one_message_revision_and_chat(db_main):
    store = db_main.messages_repository
    results = await asyncio.gather(*[store.record(**event(source=source)) for source in ["business", "userbot"] * 4])
    assert len({item.message_uuid for item in results}) == 1
    assert sum(item.new_chat for item in results) == 1
    assert len(await rows(db_main, StoredMessage)) == 1
    revisions = await rows(db_main, MessageRevision)
    assert len(revisions) == 1
    assert revisions[0].payload.startswith("enc:v1:")
    assert "Private" not in revisions[0].payload
    assert store.decode_payload(revisions[0])["text"] == "Private"
    assert len(await rows(db_main, MessageReceipt)) == 2
    assert len(await rows(db_main, HistoryUser)) == 1


@pytest.mark.asyncio
async def test_ten_edits_and_replay_preserve_all_observed_versions(db_main):
    store = db_main.messages_repository
    original = await store.record(**event())
    for index in range(1, 11):
        item = event(kind="edit", event_key=f"edit-{index}", version_at=100+index,
                     payload={"text": str(index), "media": []})
        await store.record(**item)
        await store.record(**item)
        await store.record(**(item | {"source": "userbot"}))
    revisions = await store.get_revisions(owner_id=123, message_uuid=original.message_uuid)
    assert len(revisions) == 11
    assert [store.decode_payload(row)["text"] for row in revisions] == ["Private"] + list(map(str, range(1, 11)))
    assert await store.get_revisions(owner_id=999, message_uuid=original.message_uuid) == []


@pytest.mark.asyncio
async def test_same_second_a_b_a_edits_are_not_collapsed(db_main):
    store = db_main.messages_repository
    for source in ("business", "userbot"):
        for index, content in enumerate(("A", "B", "A")):
            await store.record(**event(source=source, event_key=str(index), kind="edit",
                                       payload={"text": content}, version_at=100))
    revisions = await rows(db_main, MessageRevision)
    assert len(revisions) == 3
    assert not (await rows(db_main, StoredMessage))[0].original_seen


@pytest.mark.asyncio
async def test_unknown_delete_and_late_original_do_not_resurrect_message(db_main):
    store = db_main.messages_repository
    result = await store.record(**event(message_id=12, kind="delete", payload=None))
    assert result.new_chat
    assert (await rows(db_main, StoredMessage))[0].is_deleted
    assert await rows(db_main, MessageRevision) == []
    await store.record(**event(message_id=12, event_key="late-original"))
    head = (await rows(db_main, StoredMessage))[0]
    assert head.is_deleted and head.original_seen
    assert len(await rows(db_main, StoredMessage)) == 1


@pytest.mark.asyncio
async def test_unlocated_deletion_only_resolves_in_correct_namespace(db_main):
    store = db_main.messages_repository
    await store.record_unlocated_deletion(owner_id=123, account_user_id=456, message_id=12)
    # A legacy channel row may still exist before automatic cleanup runs.
    async with db_main.get_session_factory()() as session, session.begin():
        session.add(StoredMessage(owner_id=123, account_user_id=456, chat_id=-100111,
            message_id=12, channel_namespace=True, first_seen_at=1))
    await store.record(**event(message_id=12, chat_id=789, event_key="private"))
    records = await rows(db_main, StoredMessage)
    assert next(row for row in records if row.chat_id == 789).is_deleted
    assert not next(row for row in records if row.channel_namespace).is_deleted
    assert (await rows(db_main, PendingMessageDeletion))[0].resolved_message_uuid is not None


@pytest.mark.asyncio
async def test_stale_edit_does_not_replace_latest_and_case_is_preserved(db_main):
    store = db_main.messages_repository
    await store.record(**event(kind="edit", version_at=120, payload={"text": "UPPER"}))
    await store.record(**event(kind="edit", version_at=110, event_key="stale", payload={"text": "upper"}))
    head = (await rows(db_main, StoredMessage))[0]
    revisions = {row.uuid: row for row in await rows(db_main, MessageRevision)}
    assert store.decode_payload(revisions[head.latest_revision_uuid])["text"] == "UPPER"
    assert len(revisions) == 2


@pytest.mark.asyncio
async def test_missing_encryption_key_rolls_back_entire_ingest(db_main, monkeypatch):
    monkeypatch.delenv("DB_ENCRYPTION_KEY")
    with pytest.raises(RuntimeError):
        await db_main.messages_repository.record(**event())
    assert await rows(db_main, StoredMessage) == []
    assert await rows(db_main, DumpChatUser) == []
    assert await rows(db_main, HistoryUser) == []


@pytest.mark.asyncio
async def test_message_identity_is_scoped_to_owner_account_and_chat(db_main):
    store = db_main.messages_repository
    for changes in ({}, {"owner_id": 124}, {"account_user_id": 457}, {"chat_id": 790}):
        await store.record(**event(**changes))
    assert len(await rows(db_main, StoredMessage)) == 4
