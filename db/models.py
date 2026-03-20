from __future__ import annotations

from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Integer, UniqueConstraint
from sqlmodel import Field, SQLModel


class UsernameHistory(SQLModel, table=True):
    __tablename__ = "username_history_db"
    __table_args__ = (
        UniqueConstraint("user_id", "username_hash", name="uq_username_history_db_user_username_hash"),
    )

    uuid: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: Optional[int] = Field(default=None, sa_type=BigInteger, index=True)
    username: Optional[str] = Field(default=None)
    username_hash: Optional[str] = Field(default=None, index=True)
    date: int = Field(sa_type=BigInteger)


class User(SQLModel, table=True):
    __tablename__ = "user_db"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_db_user_id"),
    )

    uuid: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: int = Field(sa_type=BigInteger, index=True)
    username: Optional[str] = Field(default=None)
    full_name: Optional[str] = Field(default=None)
    username_hash: Optional[str] = Field(default=None, index=True)
    roles: Optional[str] = Field(default=None, index=True)

    timezone_offset: int = Field(default=3, sa_type=Integer)
    auto_update_enabled: int = Field(default=0, sa_type=Integer)

    gemini_proxy: Optional[str] = Field(default=None)
    gemini_proxy_enabled: int = Field(default=0, sa_type=Integer)
    gemini_proxy_status: int = Field(default=0, sa_type=Integer)
    gemini_proxy_checked_at: Optional[int] = Field(default=None, sa_type=BigInteger)
    gemini_proxy_last_error: Optional[str] = Field(default=None)

    update_snooze_until: Optional[int] = Field(default=None, sa_type=BigInteger)
    update_last_notified: Optional[int] = Field(default=None, sa_type=BigInteger)


class TelegramApp(SQLModel, table=True):
    __tablename__ = "app_tg_db"
    __table_args__ = (
        UniqueConstraint("user_id", "app_id", "api_hash", name="uq_app_tg_db_user_app_hash"),
    )

    uuid: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: Optional[int] = Field(default=None, sa_type=BigInteger, index=True)
    app_id: Optional[int] = Field(default=None, sa_type=BigInteger)
    api_hash: Optional[str] = Field(default=None)
    tag_name: Optional[str] = Field(default="No Name")


class Account(SQLModel, table=True):
    __tablename__ = "apps_db"
    __table_args__ = (
        UniqueConstraint("admin_id", "user_id", name="uq_apps_db_admin_user"),
    )

    uuid: UUID = Field(default_factory=uuid4, primary_key=True)
    admin_id: Optional[int] = Field(default=None, sa_type=BigInteger, index=True)
    user_id: Optional[int] = Field(default=None, sa_type=BigInteger, index=True)

    app_tg: Optional[UUID] = Field(default=None, index=True, foreign_key="app_tg_db.uuid")
    number: Optional[str] = Field(default=None)
    number_hash: Optional[str] = Field(default=None, index=True)

    alert_black_list: int = Field(default=1, sa_type=Integer)
    alert_black_list_id: int = Field(default=1, sa_type=BigInteger)

    alert_del_chat: int = Field(default=1, sa_type=Integer)
    alert_del_chat_id: int = Field(default=1, sa_type=BigInteger)

    alert_new_chat: int = Field(default=1, sa_type=Integer)
    alert_new_chat_id: int = Field(default=1, sa_type=BigInteger)

    alert_bot: int = Field(default=0, sa_type=Integer)
    alert_spoiler_media: int = Field(default=1, sa_type=Integer)

    last_update: Optional[int] = Field(default=None, sa_type=BigInteger)
    last_dialogs_count: Optional[int] = Field(default=None, sa_type=BigInteger)
    last_full_dialogs_scan: Optional[int] = Field(default=None, sa_type=BigInteger)
    baseline_sync_done: int = Field(default=0, sa_type=Integer)
    pending_delete_signature: Optional[str] = Field(default=None)
    pending_delete_count: int = Field(default=0, sa_type=Integer)
    pending_delete_since: Optional[int] = Field(default=None, sa_type=BigInteger)
    is_active: int = Field(default=1, sa_type=Integer, index=True)


class HistoryUser(SQLModel, table=True):
    __tablename__ = "history_users_db"

    uuid: UUID = Field(default_factory=uuid4, primary_key=True)
    admin_id: int = Field(sa_type=BigInteger)
    # Legacy field (historically stored chat_id).
    user_id: int = Field(sa_type=BigInteger)
    chat_id: Optional[int] = Field(default=None, sa_type=BigInteger, index=True)
    account_user_id: Optional[int] = Field(default=None, sa_type=BigInteger, index=True)
    action_id: int = Field(sa_type=Integer)
    date: int = Field(sa_type=BigInteger, index=True)


class DumpChatUser(SQLModel, table=True):
    __tablename__ = "dump_chat_user_db"
    __table_args__ = (
        UniqueConstraint("admin_id", "chat_id", name="uq_dump_chat_user_db_admin_chat"),
    )

    uuid: UUID = Field(default_factory=uuid4, primary_key=True)
    admin_id: int = Field(sa_type=BigInteger, index=True)
    chat_id: int = Field(sa_type=BigInteger, index=True)


class AccountHealth(SQLModel, table=True):
    __tablename__ = "account_health_db"

    uuid: UUID = Field(default_factory=uuid4, primary_key=True)
    account_uuid: UUID = Field(index=True, foreign_key="apps_db.uuid")
    admin_id: int = Field(sa_type=BigInteger, index=True)
    user_id: int = Field(sa_type=BigInteger, index=True)
    status: int = Field(sa_type=Integer, index=True)
    date: int = Field(sa_type=BigInteger, index=True)
    reason: Optional[str] = Field(default=None)


class VersionState(SQLModel, table=True):
    __tablename__ = "version_state_db"

    id: int = Field(default=1, primary_key=True, sa_type=Integer)
    local_version: Optional[str] = Field(default=None)
    remote_version: Optional[str] = Field(default=None)
    state: Optional[str] = Field(default=None)
    checked_at: int = Field(default=0, sa_type=BigInteger, index=True)


# Backward compatibility aliases for existing imports.
username_history_db = UsernameHistory
user_db = User
app_tg_db = TelegramApp
apps_db = Account
history_users_db = HistoryUser
dump_chat_user_db = DumpChatUser
account_health_db = AccountHealth
version_state_db = VersionState
