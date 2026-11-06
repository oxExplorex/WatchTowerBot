from __future__ import annotations

from dataclasses import dataclass
import json
import hashlib
import time
from uuid import UUID

from sqlalchemy import BigInteger, case, exists, func, literal, or_, select, union

from db.message_models import MessageReceipt, MessageRevision, PendingMessageDeletion, StoredMessage
from db.models import DumpChatUser, HistoryUser
from db.repositories.base import conflict_insert
from db.repositories.media_repo import enqueue_attachments
from db.repositories.personal_repo import lock_owner
from db.repositories.account_locks import lock_account, unique_account
from db.account_operation_models import AccountOperation
from core.personal_crypto import context, live_fingerprint, open_text, seal_text
from db.chat_policy_models import ArchiveChatPolicy
from db.repositories.chat_policy_repo import observe_policies
from utils.archive_policy import IGNORED_CHAT_IDS, archive_allowed
from utils.crypto_store import decrypt_text, encrypt_text, message_fingerprint


@dataclass(frozen=True)
class IngestResult:
    message_uuid: UUID
    new_chat: bool
    new_revision: bool = False
    owner_id: int | None = None


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

    async def statistics(self, owner_id):
        from db.media_models import MessageAttachment
        from db.history_models import HistoryChat, HistoryRange
        from db.models import Account

        scope = (StoredMessage.owner_id == owner_id, StoredMessage.chat_id > 0)
        async with self._session_factory()() as session:
            row = (await session.execute(select(
                func.count().label("messages"),
                func.coalesce(func.sum(case((StoredMessage.is_edited, 1), else_=0)), 0).label("edited"),
                func.coalesce(func.sum(case((StoredMessage.is_deleted, 1), else_=0)), 0).label("deleted"),
                func.coalesce(func.sum(case((StoredMessage.history_missing_at.is_not(None), 1), else_=0)), 0).label("missing")
            ).select_from(StoredMessage).where(*scope))).one()
            result = dict(row._mapping)
            result["revisions"] = await session.scalar(select(func.count()).select_from(MessageRevision)
                .join(StoredMessage, StoredMessage.uuid == MessageRevision.message_uuid).where(*scope))
            result["content_bytes"] = await session.scalar(select(func.coalesce(func.sum(func.length(MessageRevision.payload)), 0))
                .join(StoredMessage, StoredMessage.uuid == MessageRevision.message_uuid).where(*scope))
            stored_chats = select(StoredMessage.account_user_id, StoredMessage.chat_id).where(*scope).distinct()
            result["chats_with_messages"] = await session.scalar(select(func.count()).select_from(stored_chats.subquery()))
            known_chats = union(stored_chats, select(Account.user_id, DumpChatUser.chat_id).join(
                DumpChatUser, DumpChatUser.admin_id == Account.user_id).where(
                    Account.admin_id == owner_id, DumpChatUser.chat_id > 0))
            result["chats"] = await session.scalar(select(func.count()).select_from(known_chats.subquery()))
            attachments = (await session.execute(select(MessageAttachment.status, func.count()).join(
                MessageRevision, MessageRevision.uuid == MessageAttachment.revision_uuid).join(
                StoredMessage, StoredMessage.uuid == MessageRevision.message_uuid
            ).where(*scope).group_by(MessageAttachment.status))).all()
            statuses = dict(attachments)
            result["attachments"] = sum(statuses.values())
            result["content_bytes"] += await session.scalar(select(func.coalesce(func.sum(func.length(MessageAttachment.sources)), 0))
                .join(MessageRevision, MessageRevision.uuid == MessageAttachment.revision_uuid)
                .join(StoredMessage, StoredMessage.uuid == MessageRevision.message_uuid).where(*scope))
            result.update(media_stored=statuses.get("stored", 0),
                          media_pending=statuses.get("pending", 0) + statuses.get("downloading", 0),
                          media_failed=statuses.get("failed", 0))
            checked = or_(HistoryChat.reached_start, exists().where(
                HistoryRange.account_uuid == HistoryChat.account_uuid, HistoryRange.chat_id == HistoryChat.chat_id))
            total, reached, inspected = (await session.execute(select(func.count(), func.coalesce(func.sum(case(
                (HistoryChat.reached_start, 1), else_=0)), 0), func.coalesce(func.sum(case((checked, 1), else_=0)), 0))
                .select_from(HistoryChat).join(
                Account, Account.uuid == HistoryChat.account_uuid
            ).where(Account.admin_id == owner_id, Account.is_active == 1, HistoryChat.excluded == False))).one()
            result.update(history_chats=total, history_reached=reached, history_checked=inspected)
            return result

    async def media_references(self, owner_id):
        from db.avatar_models import ChatAvatar
        from db.media_models import MessageAttachment

        attachments = select(MessageAttachment.blob_key).join(MessageRevision).join(StoredMessage).where(
            StoredMessage.owner_id == owner_id, MessageAttachment.owner_id == owner_id,
            MessageAttachment.status == "stored", MessageAttachment.blob_key.is_not(None))
        avatars = select(ChatAvatar.blob_key).where(ChatAvatar.owner_id == owner_id,
            ChatAvatar.status == "stored", ChatAvatar.blob_key.is_not(None))
        async with self._session_factory()() as session:
            return list(await session.scalars(union(attachments, avatars)))

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
                     channel_namespace: bool = False, require_account: bool = False,
                     historical: bool = False, chat_kind: str | None = None) -> IngestResult | None:
        if channel_namespace or not archive_allowed(chat_id, chat_kind or "private"):
            return None
        if kind not in {"new", "edit", "delete"} or message_id <= 0:
            raise ValueError("Unsupported message event")
        if kind != "delete" and payload is None:
            raise ValueError("Message content is required")
        now = time.time_ns() // 1000
        async with self._session_factory()() as session, session.begin():
            await lock_account(session, account_user_id)
            if require_account:
                account = await unique_account(session, account_user_id)
                if account is None or not account.is_active:
                    return None
                owner_id = int(account.admin_id)
            elif await session.scalar(select(exists().where(
                    AccountOperation.account_user_id == account_user_id, AccountOperation.kind == "delete",
                    AccountOperation.status.in_({"deleting", "removing_session", "complete"})))):
                return None
            owner_key = await lock_owner(session, owner_id)
            if await session.scalar(select(exists().where(ArchiveChatPolicy.chat_id == chat_id,
                                                           ArchiveChatPolicy.kind == "bot"))):
                return None
            await observe_policies(session, account_user_id, [(chat_id, chat_kind or "private")])
            policy = await session.get(ArchiveChatPolicy, (account_user_id, chat_id))
            if policy.kind == "bot":
                return None
            if historical:
                if owner_key is None:
                    return None
                if await session.scalar(select(exists().where(
                        AccountOperation.active_account_id == account_user_id,
                        AccountOperation.status.in_({"preparing", "activating", "deleting", "removing_session"})))):
                    return None
            await self._lock(session, owner_id, account_user_id, message_id)
            # Native upsert arbitrates races across sources/processes, not just tasks.
            # Old snapshots are archive content, not proof that the dialog still exists.
            # A queued history page may finish after a scan has observed its deletion.
            new_chat = False
            if not historical:
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
            if payload is not None:
                # Reappearance is meaningful even when the content event is a replay.
                row.history_missing_at = None
                row.is_edited = row.is_edited or kind == "edit"
            receipt = await session.scalar(select(MessageReceipt).where(
                MessageReceipt.message_uuid == row.uuid, MessageReceipt.source == source,
                MessageReceipt.event_key == event_key))
            if receipt is not None:
                if payload is not None and receipt.revision_uuid is not None:
                    await enqueue_attachments(session, receipt.revision_uuid, payload,
                                              owner_id=owner_id, account_user_id=account_user_id, source=source)
                return IngestResult(row.uuid, new_chat, owner_id=owner_id)
            revision = None
            new_revision = False
            if kind == "delete":
                row.is_deleted = True
                row.history_missing_at = None
                row.deleted_observed_at = row.deleted_observed_at or now
            else:
                timestamp = version_at if version_at is not None else sent_at or 0
                if historical and row.latest_revision_uuid is not None and row.latest_version_at is not None and row.latest_version_at >= timestamp:
                    return IngestResult(row.uuid, new_chat, owner_id=owner_id)
                revision_kind = "snapshot" if historical else kind
                serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                # File IDs can differ between the Bot API and MTProto sessions.
                comparable = comparable_payload(payload)
                fingerprint = personal_fingerprint(owner_id, comparable) if owner_key else message_fingerprint(comparable)
                seen_from_source = exists(select(MessageReceipt.uuid).where(
                    MessageReceipt.revision_uuid == MessageRevision.uuid, MessageReceipt.source == source))
                revision_query = select(MessageRevision).where(
                    MessageRevision.message_uuid == row.uuid, MessageRevision.kind.in_({revision_kind, "snapshot"}),
                    MessageRevision.version_at == timestamp, MessageRevision.fingerprint == fingerprint)
                if kind == "edit":
                    revision_query = revision_query.where(~seen_from_source)
                revision = await session.scalar(revision_query.order_by(MessageRevision.revision_no).limit(1))
                if revision is None and row.latest_revision_uuid is not None:
                    latest = await session.get(MessageRevision, row.latest_revision_uuid)
                    if latest.kind in {revision_kind, "snapshot"} and latest.version_at == timestamp and latest.fingerprint == fingerprint:
                        revision = latest
                if revision is None:
                    last_number = await session.scalar(select(func.max(MessageRevision.revision_no)).where(MessageRevision.message_uuid == row.uuid))
                    revision = MessageRevision(message_uuid=row.uuid, kind=revision_kind, version_at=timestamp,
                                               observed_at=now, payload="", fingerprint=fingerprint,
                                               encryption_version=2 if owner_key else 1,
                                               revision_no=(last_number or 0) + 1)
                    revision.payload = (seal_text(owner_key.public_key, serialized, context(owner_id, f"revision:{revision.uuid}"))
                                        if owner_key else encrypt_text(serialized))
                    session.add(revision)
                    await session.flush()
                    new_revision = True
                row.original_seen = row.original_seen or (kind == "new" and not historical)
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
                        StoredMessage.message_id == message_id, StoredMessage.channel_namespace == False,
                        StoredMessage.chat_id > 0, StoredMessage.chat_id.not_in(IGNORED_CHAT_IDS)))).all()
                    if len(candidates) == 1:
                        row.is_deleted = True
                        row.deleted_observed_at = row.deleted_observed_at or pending.observed_at
                        pending.resolved_message_uuid = row.uuid
            return IngestResult(row.uuid, new_chat, new_revision, owner_id)

    async def record_unlocated_deletion(self, *, owner_id: int, account_user_id: int, message_id: int,
                                       require_account: bool = False) -> None:
        async with self._session_factory()() as session, session.begin():
            await lock_account(session, account_user_id)
            if require_account:
                account = await unique_account(session, account_user_id)
                if account is None or not account.is_active:
                    return
                owner_id = int(account.admin_id)
            elif await session.scalar(select(exists().where(
                    AccountOperation.account_user_id == account_user_id, AccountOperation.kind == "delete",
                    AccountOperation.status.in_({"deleting", "removing_session", "complete"})))):
                return
            await lock_owner(session, owner_id)
            await self._lock(session, owner_id, account_user_id, message_id)
            insert = conflict_insert(session, PendingMessageDeletion).values(
                owner_id=owner_id, account_user_id=account_user_id, message_id=message_id,
                observed_at=time.time_ns() // 1000)
            await session.execute(insert.on_conflict_do_nothing(index_elements=["owner_id", "account_user_id", "message_id"]))
            candidates = (await session.scalars(select(StoredMessage).where(
                StoredMessage.owner_id == owner_id, StoredMessage.account_user_id == account_user_id,
                StoredMessage.message_id == message_id, StoredMessage.channel_namespace == False,
                StoredMessage.chat_id > 0, StoredMessage.chat_id.not_in(IGNORED_CHAT_IDS), ~exists().where(
                    ArchiveChatPolicy.account_user_id == account_user_id,
                    ArchiveChatPolicy.chat_id == StoredMessage.chat_id, ArchiveChatPolicy.kind != "private")
                ).with_for_update())).all()
            if len(candidates) == 1:
                pending = await session.scalar(select(PendingMessageDeletion).filter_by(
                    owner_id=owner_id, account_user_id=account_user_id, message_id=message_id))
                candidates[0].is_deleted = True
                candidates[0].history_missing_at = None
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
