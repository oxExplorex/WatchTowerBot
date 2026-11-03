from __future__ import annotations

from dataclasses import dataclass
import json
import hashlib
import time
from uuid import UUID

from sqlalchemy import BigInteger, exists, func, literal, select

from db.message_models import MessageReceipt, MessageRevision, PendingMessageDeletion, StoredMessage
from db.models import DumpChatUser, HistoryUser
from db.repositories.base import conflict_insert
from db.repositories.media_repo import enqueue_attachments
from db.repositories.personal_repo import lock_owner
from core.personal_crypto import context, live_fingerprint, open_text, seal_text
from utils.crypto_store import decrypt_text, encrypt_text, message_fingerprint


@dataclass(frozen=True)
class IngestResult:
    message_uuid: UUID
    new_chat: bool
    new_revision: bool = False


def comparable_payload(payload):
    comparable = dict(payload)
    comparable.pop("link", None)
    comparable.pop("sender", None)
    comparable["media"] = [{k: v for k, v in item.items() if k != "file_id"} for item in payload.get("media", [])]
    return json.dumps(comparable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def personal_fingerprint(owner_id, comparable):
    return live_fingerprint(f"owner:{owner_id}\0{comparable}")


class MessagesRepository:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    @staticmethod
    async def _lock(session, owner_id: int, account_user_id: int, message_id: int) -> None:
        if session.get_bind().dialect.name == "postgresql":
            identity = f"message:{owner_id}:{account_user_id}:{message_id}".encode()
            key = int.from_bytes(hashlib.sha256(identity).digest()[:8], "big", signed=True)
            await session.execute(select(func.pg_advisory_xact_lock(literal(key, type_=BigInteger))))

    async def record(self, *, owner_id: int, account_user_id: int, chat_id: int,
                     message_id: int, source: str, event_key: str, kind: str,
                     payload: dict | None = None, sent_at: int | None = None,
                     version_at: int | None = None, sender_id: int | None = None,
                     channel_namespace: bool = False) -> IngestResult:
        if kind not in {"new", "edit", "delete"} or message_id <= 0:
            raise ValueError("Unsupported message event")
        if kind != "delete" and payload is None:
            raise ValueError("Message content is required")
        now = time.time_ns() // 1000
        async with self._session_factory()() as session, session.begin():
            owner_key = await lock_owner(session, owner_id)
            await self._lock(session, owner_id, account_user_id, message_id)
            # Native upsert arbitrates races across sources/processes, not just tasks.
            chat_insert = conflict_insert(session, DumpChatUser).values(admin_id=account_user_id, chat_id=chat_id)
            chat_insert = chat_insert.on_conflict_do_nothing(index_elements=["admin_id", "chat_id"]).returning(DumpChatUser.uuid)
            new_chat = (await session.execute(chat_insert)).scalar_one_or_none() is not None
            identity = dict(owner_id=owner_id, account_user_id=account_user_id, chat_id=chat_id, message_id=message_id)
            insert = conflict_insert(session, StoredMessage).values(**identity, first_seen_at=now, channel_namespace=channel_namespace)
            await session.execute(insert.on_conflict_do_nothing(index_elements=list(identity)))
            row = (await session.execute(select(StoredMessage).filter_by(**identity).with_for_update())).scalar_one()
            if new_chat:
                session.add(HistoryUser(admin_id=owner_id, user_id=chat_id, chat_id=chat_id,
                                        account_user_id=account_user_id, action_id=1, date=now // 1_000_000))
            receipt = await session.scalar(select(MessageReceipt).where(
                MessageReceipt.message_uuid == row.uuid, MessageReceipt.source == source,
                MessageReceipt.event_key == event_key))
            if receipt is not None:
                if payload is not None and receipt.revision_uuid is not None:
                    await enqueue_attachments(session, receipt.revision_uuid, payload,
                                              owner_id=owner_id, account_user_id=account_user_id, source=source)
                return IngestResult(row.uuid, new_chat)
            revision = None
            new_revision = False
            if kind == "delete":
                row.is_deleted = True
                row.deleted_observed_at = row.deleted_observed_at or now
            else:
                serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                # File IDs can differ between the Bot API and MTProto sessions.
                comparable = comparable_payload(payload)
                fingerprint = personal_fingerprint(owner_id, comparable) if owner_key else message_fingerprint(comparable)
                timestamp = version_at if version_at is not None else sent_at or 0
                seen_from_source = exists(select(MessageReceipt.uuid).where(
                    MessageReceipt.revision_uuid == MessageRevision.uuid, MessageReceipt.source == source))
                revision_query = select(MessageRevision).where(
                    MessageRevision.message_uuid == row.uuid, MessageRevision.kind == kind,
                    MessageRevision.version_at == timestamp, MessageRevision.fingerprint == fingerprint)
                if kind == "edit":
                    revision_query = revision_query.where(~seen_from_source)
                revision = await session.scalar(revision_query.order_by(MessageRevision.revision_no).limit(1))
                if revision is None and row.latest_revision_uuid is not None:
                    latest = await session.get(MessageRevision, row.latest_revision_uuid)
                    if latest.kind == kind and latest.version_at == timestamp and latest.fingerprint == fingerprint:
                        revision = latest
                if revision is None:
                    last_number = await session.scalar(select(func.max(MessageRevision.revision_no)).where(MessageRevision.message_uuid == row.uuid))
                    revision = MessageRevision(message_uuid=row.uuid, kind=kind, version_at=timestamp,
                                               observed_at=now, payload="", fingerprint=fingerprint,
                                               encryption_version=2 if owner_key else 1,
                                               revision_no=(last_number or 0) + 1)
                    revision.payload = (seal_text(owner_key.public_key, serialized, context(owner_id, f"revision:{revision.uuid}"))
                                        if owner_key else encrypt_text(serialized))
                    session.add(revision)
                    await session.flush()
                    new_revision = True
                row.original_seen = row.original_seen or kind == "new"
                row.is_edited = row.is_edited or kind == "edit"
                row.sent_at = row.sent_at if row.sent_at is not None else sent_at
                row.sender_id = row.sender_id if row.sender_id is not None else sender_id
                if row.latest_version_at is None or timestamp > row.latest_version_at or (
                    timestamp == row.latest_version_at and new_revision and kind == "edit"
                ):
                    row.latest_revision_uuid = revision.uuid
                    row.latest_version_at = timestamp
            session.add(MessageReceipt(message_uuid=row.uuid, revision_uuid=revision.uuid if revision else None,
                                       source=source, event_key=event_key))
            if revision is not None:
                await enqueue_attachments(session, revision.uuid, payload,
                                          owner_id=owner_id, account_user_id=account_user_id, source=source)
            if not channel_namespace:
                pending = await session.scalar(select(PendingMessageDeletion).where(
                    PendingMessageDeletion.owner_id == owner_id,
                    PendingMessageDeletion.account_user_id == account_user_id,
                    PendingMessageDeletion.message_id == message_id).with_for_update())
                if pending is not None:
                    # MTProto private/basic-group IDs share one account namespace.
                    candidates = (await session.scalars(select(StoredMessage).where(
                        StoredMessage.owner_id == owner_id, StoredMessage.account_user_id == account_user_id,
                        StoredMessage.message_id == message_id, StoredMessage.channel_namespace == False))).all()
                    if len(candidates) == 1:
                        row.is_deleted = True
                        row.deleted_observed_at = row.deleted_observed_at or pending.observed_at
                        pending.resolved_message_uuid = row.uuid
            return IngestResult(row.uuid, new_chat, new_revision)

    async def record_unlocated_deletion(self, *, owner_id: int, account_user_id: int, message_id: int) -> None:
        async with self._session_factory()() as session, session.begin():
            await self._lock(session, owner_id, account_user_id, message_id)
            insert = conflict_insert(session, PendingMessageDeletion).values(
                owner_id=owner_id, account_user_id=account_user_id, message_id=message_id,
                observed_at=time.time_ns() // 1000)
            await session.execute(insert.on_conflict_do_nothing(index_elements=["owner_id", "account_user_id", "message_id"]))
            candidates = (await session.scalars(select(StoredMessage).where(
                StoredMessage.owner_id == owner_id, StoredMessage.account_user_id == account_user_id,
                StoredMessage.message_id == message_id, StoredMessage.channel_namespace == False).with_for_update())).all()
            if len(candidates) == 1:
                pending = await session.scalar(select(PendingMessageDeletion).filter_by(
                    owner_id=owner_id, account_user_id=account_user_id, message_id=message_id))
                candidates[0].is_deleted = True
                candidates[0].deleted_observed_at = candidates[0].deleted_observed_at or pending.observed_at
                pending.resolved_message_uuid = candidates[0].uuid

    async def get_revisions(self, *, owner_id: int, message_uuid: UUID) -> list[MessageRevision]:
        async with self._session_factory()() as session:
            return list((await session.scalars(select(MessageRevision).join(
                StoredMessage, StoredMessage.uuid == MessageRevision.message_uuid).where(
                    StoredMessage.owner_id == owner_id, StoredMessage.uuid == message_uuid
                ).order_by(MessageRevision.version_at, MessageRevision.revision_no))).all())

    @staticmethod
    def decode_payload(revision: MessageRevision, *, owner_id=None, private_key=None) -> dict:
        if revision.encryption_version == 2:
            if owner_id is None or private_key is None:
                raise PermissionError("Personal secret is required to read archived messages")
            return json.loads(open_text(private_key, revision.payload, context(owner_id, f"revision:{revision.uuid}")))
        if revision.encryption_version != 1:
            raise ValueError("Unsupported message encryption version")
        return json.loads(decrypt_text(revision.payload))
