"""Message content is encrypted; Telegram identifiers remain queryable."""
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, UniqueConstraint
from sqlmodel import Field, SQLModel


class StoredMessage(SQLModel, table=True):
    __tablename__ = "stored_message"
    __table_args__ = (UniqueConstraint("owner_id", "account_user_id", "chat_id", "message_id", name="uq_stored_message_identity"),)

    uuid: UUID = Field(default_factory=uuid4, primary_key=True)
    owner_id: int = Field(sa_type=BigInteger, index=True)
    account_user_id: int = Field(sa_type=BigInteger, index=True)
    chat_id: int = Field(sa_type=BigInteger, index=True)
    message_id: int = Field(sa_type=BigInteger, index=True)
    channel_namespace: bool = False
    sender_id: int | None = Field(default=None, sa_type=BigInteger)
    sent_at: int | None = Field(default=None, sa_type=BigInteger)
    first_seen_at: int = Field(sa_type=BigInteger)
    original_seen: bool = False
    is_edited: bool = False
    is_deleted: bool = False
    deleted_observed_at: int | None = Field(default=None, sa_type=BigInteger)
    latest_revision_uuid: UUID | None = None
    latest_version_at: int | None = Field(default=None, sa_type=BigInteger)


class MessageRevision(SQLModel, table=True):
    __tablename__ = "message_revision"
    __table_args__ = (UniqueConstraint("message_uuid", "revision_no", name="uq_message_revision_number"),)

    uuid: UUID = Field(default_factory=uuid4, primary_key=True)
    message_uuid: UUID = Field(foreign_key="stored_message.uuid", index=True)
    revision_no: int
    kind: str
    version_at: int = Field(sa_type=BigInteger)
    observed_at: int = Field(sa_type=BigInteger)
    payload: str
    fingerprint: str = Field(index=True)
    encryption_version: int = 1


class MessageReceipt(SQLModel, table=True):
    __tablename__ = "message_receipt"
    __table_args__ = (UniqueConstraint("message_uuid", "source", "event_key", name="uq_message_receipt_event"),)

    uuid: UUID = Field(default_factory=uuid4, primary_key=True)
    message_uuid: UUID = Field(foreign_key="stored_message.uuid", index=True)
    revision_uuid: UUID | None = Field(default=None, foreign_key="message_revision.uuid", index=True)
    source: str
    event_key: str


class PendingMessageDeletion(SQLModel, table=True):
    __tablename__ = "pending_message_deletion"
    __table_args__ = (UniqueConstraint("owner_id", "account_user_id", "message_id", name="uq_pending_message_deletion"),)

    uuid: UUID = Field(default_factory=uuid4, primary_key=True)
    owner_id: int = Field(sa_type=BigInteger)
    account_user_id: int = Field(sa_type=BigInteger, index=True)
    message_id: int = Field(sa_type=BigInteger, index=True)
    observed_at: int = Field(sa_type=BigInteger)
    resolved_message_uuid: UUID | None = Field(default=None, foreign_key="stored_message.uuid")
