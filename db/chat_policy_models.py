"""Observed chat types; no titles, message contents or Telegram credentials."""
from sqlalchemy import BigInteger
from sqlmodel import Field, SQLModel


class ArchiveChatPolicy(SQLModel, table=True):
    __tablename__ = "archive_chat_policy"
    account_user_id: int = Field(primary_key=True, sa_type=BigInteger)
    chat_id: int = Field(primary_key=True, sa_type=BigInteger, index=True)
    kind: str
    retry_at: int = Field(default=0, sa_type=BigInteger)
