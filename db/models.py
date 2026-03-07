from typing import Optional
from uuid import uuid4

from sqlalchemy import BigInteger, Integer
from sqlmodel import Field, SQLModel


class username_history_db(SQLModel, table=True):
    uuid: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: Optional[int] = Field(default=None, sa_type=BigInteger, index=True)
    username: Optional[str] = Field(default=None)
    date: int = Field(sa_type=BigInteger)


class user_db(SQLModel, table=True):
    uuid: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: int = Field(sa_type=BigInteger, index=True)
    username: Optional[str] = Field(default=None)
    full_name: Optional[str] = Field(default=None)
    roles: Optional[str] = Field(default=None, index=True)


class app_tg_db(SQLModel, table=True):
    uuid: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: Optional[int] = Field(default=None, sa_type=BigInteger, index=True)
    app_id: Optional[int] = Field(default=None, sa_type=BigInteger)
    api_hash: Optional[str] = Field(default=None)
    tag_name: Optional[str] = Field(default="No Name")


class apps_db(SQLModel, table=True):
    uuid: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    admin_id: Optional[int] = Field(default=None, sa_type=BigInteger, index=True)
    user_id: Optional[int] = Field(default=None, sa_type=BigInteger, index=True)

    app_tg: Optional[str] = Field(default=None, index=True)
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
    uuid: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    admin_id: int = Field(sa_type=BigInteger)
    user_id: int = Field(sa_type=BigInteger)
    action_id: int = Field(sa_type=Integer)
    date: int = Field(sa_type=BigInteger)


class dump_chat_user_db(SQLModel, table=True):
    uuid: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    admin_id: int = Field(sa_type=BigInteger, index=True)
    chat_id: int = Field(sa_type=BigInteger, index=True)


class account_health_db(SQLModel, table=True):
    uuid: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    account_uuid: str = Field(index=True)
    admin_id: int = Field(sa_type=BigInteger, index=True)
    user_id: int = Field(sa_type=BigInteger, index=True)
    status: int = Field(sa_type=Integer, index=True)
    date: int = Field(sa_type=BigInteger, index=True)
    reason: Optional[str] = Field(default=None)
