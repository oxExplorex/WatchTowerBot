from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Integer
from sqlmodel import Field, SQLModel


class username_history_db(SQLModel, table=True):
    uuid: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: Optional[int] = Field(default=None, sa_type=BigInteger, index=True)
    username: Optional[str] = Field(default=None)
    date: int = Field(sa_type=BigInteger)


class user_db(SQLModel, table=True):
    uuid: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: int = Field(sa_type=BigInteger, index=True)
    username: Optional[str] = Field(default=None)
    full_name: Optional[str] = Field(default=None)
    roles: Optional[str] = Field(default=None, index=True)

    timezone_offset: int = Field(default=3, sa_type=Integer)
    auto_update_enabled: int = Field(default=0, sa_type=Integer)

    # Gemini proxy settings (1 user/admin -> 1 proxy)
    gemini_proxy: Optional[str] = Field(default=None)
    gemini_proxy_enabled: int = Field(default=0, sa_type=Integer)
    gemini_proxy_status: int = Field(default=0, sa_type=Integer)
    gemini_proxy_checked_at: Optional[int] = Field(default=None, sa_type=BigInteger)
    gemini_proxy_last_error: Optional[str] = Field(default=None)

    update_snooze_until: Optional[int] = Field(default=None, sa_type=BigInteger)
    update_last_notified: Optional[int] = Field(default=None, sa_type=BigInteger)


class app_tg_db(SQLModel, table=True):
    uuid: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: Optional[int] = Field(default=None, sa_type=BigInteger, index=True)
    app_id: Optional[int] = Field(default=None, sa_type=BigInteger)
    api_hash: Optional[str] = Field(default=None)
    tag_name: Optional[str] = Field(default="No Name")


class apps_db(SQLModel, table=True):
    uuid: UUID = Field(default_factory=uuid4, primary_key=True)
    admin_id: Optional[int] = Field(default=None, sa_type=BigInteger, index=True)
    user_id: Optional[int] = Field(default=None, sa_type=BigInteger, index=True)

    app_tg: Optional[UUID] = Field(default=None, index=True)
    number: Optional[str] = Field(default=None)

    alert_black_list: int = Field(default=1, sa_type=Integer)
    alert_black_list_id: int = Field(default=1, sa_type=BigInteger)

    alert_del_chat: int = Field(default=1, sa_type=Integer)
    alert_del_chat_id: int = Field(default=1, sa_type=BigInteger)

    alert_new_chat: int = Field(default=1, sa_type=Integer)
    alert_new_chat_id: int = Field(default=1, sa_type=BigInteger)

    alert_bot: int = Field(default=0, sa_type=Integer)
    # Toggle for forwarding disappearing/spoiler media to admin notifications.
    alert_spoiler_media: int = Field(default=1, sa_type=Integer)

    last_update: Optional[int] = Field(default=None, sa_type=BigInteger)
    # Last dialogs_count snapshot used for lightweight periodic checks.
    last_dialogs_count: Optional[int] = Field(default=None, sa_type=BigInteger)
    # Last timestamp when full dialogs iteration was executed.
    last_full_dialogs_scan: Optional[int] = Field(default=None, sa_type=BigInteger)
    is_active: int = Field(default=1, sa_type=Integer, index=True)


class history_users_db(SQLModel, table=True):
    uuid: UUID = Field(default_factory=uuid4, primary_key=True)
    admin_id: int = Field(sa_type=BigInteger)
    user_id: int = Field(sa_type=BigInteger)
    action_id: int = Field(sa_type=Integer)
    date: int = Field(sa_type=BigInteger)


class dump_chat_user_db(SQLModel, table=True):
    uuid: UUID = Field(default_factory=uuid4, primary_key=True)
    admin_id: int = Field(sa_type=BigInteger, index=True)
    chat_id: int = Field(sa_type=BigInteger, index=True)


class account_health_db(SQLModel, table=True):
    uuid: UUID = Field(default_factory=uuid4, primary_key=True)
    account_uuid: UUID = Field(index=True)
    admin_id: int = Field(sa_type=BigInteger, index=True)
    user_id: int = Field(sa_type=BigInteger, index=True)
    status: int = Field(sa_type=Integer, index=True)
    date: int = Field(sa_type=BigInteger, index=True)
    reason: Optional[str] = Field(default=None)


class version_state_db(SQLModel, table=True):
    id: int = Field(default=1, primary_key=True, sa_type=Integer)
    local_version: Optional[str] = Field(default=None)
    remote_version: Optional[str] = Field(default=None)
    state: Optional[str] = Field(default=None)
    checked_at: int = Field(default=0, sa_type=BigInteger, index=True)
