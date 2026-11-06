"""Observed avatar occurrences; image bytes use personal WTM2."""
from uuid import UUID, uuid4
from sqlalchemy import BigInteger, Index, text
from sqlmodel import Field, SQLModel


class ChatAvatar(SQLModel, table=True):
    __tablename__ = "chat_avatar"
    __table_args__ = (Index("uq_chat_avatar_current", "owner_id", "account_user_id", "user_id", unique=True,
                           sqlite_where=text("ended_at IS NULL"), postgresql_where=text("ended_at IS NULL")),)
    uuid: UUID = Field(default_factory=uuid4, primary_key=True)
    owner_id: int = Field(sa_type=BigInteger, index=True)
    account_user_id: int = Field(sa_type=BigInteger, index=True)
    user_id: int = Field(sa_type=BigInteger)
    photo_key: str
    file_id: str | None = None  # Server-encrypted only while download is pending; cleared afterwards.
    source: str = "userbot"
    blob_key: str | None = None
    status: str = "pending"
    next_attempt_at: int = Field(default=0, sa_type=BigInteger)
    lease_until: int = Field(default=0, sa_type=BigInteger)
    lease_token: UUID | None = None
    state_version: int = 0
    updated_at: int = Field(default=0, sa_type=BigInteger)
    first_seen_at: int = Field(default=0, sa_type=BigInteger)  # Microseconds, observation time.
    ended_at: int | None = Field(default=None, sa_type=BigInteger)
