"""Durable account actions; no passwords or usable private keys are stored here."""
from uuid import UUID, uuid4

from sqlalchemy import BigInteger
from sqlmodel import Field, SQLModel


class AccountOperation(SQLModel, table=True):
    __tablename__ = "account_operation"

    uuid: UUID = Field(default_factory=uuid4, primary_key=True)
    account_uuid: UUID = Field(index=True)
    account_user_id: int = Field(sa_type=BigInteger, index=True)
    owner_id: int = Field(sa_type=BigInteger, index=True)
    actor_id: int = Field(sa_type=BigInteger, index=True)
    kind: str
    status: str = Field(index=True)
    # NULL releases the slot; terminal requests remain available to old buttons.
    active_account_id: int | None = Field(default=None, sa_type=BigInteger, unique=True)
    target_app_uuid: UUID | None = None
    session_number: str | None = None  # Existing enc:v1 value, used only for deferred cleanup.
    created_at: int = Field(sa_type=BigInteger)
    updated_at: int = Field(sa_type=BigInteger)
    run_token: UUID | None = None
    last_error: str | None = None
    owner_notified: bool = False
    result_notified: bool = False
    notify_after: int = Field(default=0, sa_type=BigInteger)


class TransferRevision(SQLModel, table=True):
    __tablename__ = "account_transfer_revision"

    operation_uuid: UUID = Field(primary_key=True, foreign_key="account_operation.uuid")
    revision_uuid: UUID = Field(primary_key=True)
    original_payload: str
    original_version: int
    payload: str
    fingerprint: str


class TransferAttachment(SQLModel, table=True):
    __tablename__ = "account_transfer_attachment"

    operation_uuid: UUID = Field(primary_key=True, foreign_key="account_operation.uuid")
    attachment_uuid: UUID = Field(primary_key=True)
    original_snapshot: str
    original_state_version: int
    sources: str
    file_key: str
    blob_key: str | None = None
    stored_size: int | None = Field(default=None, sa_type=BigInteger)
    encryption_version: int = 1
    sources_encryption_version: int = 1


class ArchiveBlobCleanup(SQLModel, table=True):
    __tablename__ = "archive_blob_cleanup"

    owner_id: int = Field(primary_key=True, sa_type=BigInteger)
    blob_key: str = Field(primary_key=True)
