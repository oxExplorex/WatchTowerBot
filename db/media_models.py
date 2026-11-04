from uuid import UUID, uuid4

from sqlalchemy import BigInteger, UniqueConstraint
from sqlmodel import Field, SQLModel


class MessageAttachment(SQLModel, table=True):
    __tablename__ = "message_attachment"
    __table_args__ = (UniqueConstraint("revision_uuid", "position", name="uq_attachment_revision_position"),)

    uuid: UUID = Field(default_factory=uuid4, primary_key=True)
    revision_uuid: UUID = Field(foreign_key="message_revision.uuid", index=True)
    position: int
    owner_id: int = Field(sa_type=BigInteger, index=True)
    file_key: str = Field(index=True)
    sources: str  # Encrypted source-specific file IDs, never public download URLs.
    expected_size: int | None = Field(default=None, sa_type=BigInteger)
    blob_key: str | None = None
    stored_size: int | None = Field(default=None, sa_type=BigInteger)
    encryption_version: int = 1
    sources_encryption_version: int = 1
    status: str = Field(default="pending", index=True)
    attempts: int = 0
    next_attempt_at: int = Field(default=0, sa_type=BigInteger)
    lease_token: UUID | None = None
    lease_until: int = Field(default=0, sa_type=BigInteger)
    last_error: str | None = None
    state_version: int = 0
