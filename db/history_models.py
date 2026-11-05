"""History coverage describes inspected windows, not existence of every message ID."""
from uuid import UUID

from sqlalchemy import BigInteger
from sqlmodel import Field, SQLModel


class HistoryRun(SQLModel, table=True):
    __tablename__ = "history_run"
    account_uuid: UUID = Field(primary_key=True)
    account_user_id: int = Field(sa_type=BigInteger, index=True)
    next_run_at: int = Field(default=0, sa_type=BigInteger)


class HistoryChat(SQLModel, table=True):
    __tablename__ = "history_chat"
    account_uuid: UUID = Field(primary_key=True)
    chat_id: int = Field(primary_key=True, sa_type=BigInteger)
    known_top_id: int = 0
    oldest_message_id: int | None = None
    reached_start: bool = False
    excluded: bool = False
    turn: int = 0
    last_attempt_at: int = Field(default=0, sa_type=BigInteger)
    last_head_at: int = Field(default=0, sa_type=BigInteger)
    retry_at: int = Field(default=0, sa_type=BigInteger)
    last_error: str | None = None


class HistoryRange(SQLModel, table=True):
    __tablename__ = "history_range"
    account_uuid: UUID = Field(primary_key=True)
    chat_id: int = Field(primary_key=True, sa_type=BigInteger)
    low_id: int = Field(primary_key=True)
    high_id: int


class TelegramCooldown(SQLModel, table=True):
    __tablename__ = "telegram_cooldown"
    account_user_id: int = Field(primary_key=True, sa_type=BigInteger)
    blocked_until: int = Field(default=0, sa_type=BigInteger)
    media_next_at: int = Field(default=0, sa_type=BigInteger)
