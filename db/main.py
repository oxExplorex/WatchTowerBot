import os
import re
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional
from uuid import UUID

import asyncpg
from sqlalchemy import func, inspect, select, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.sql.sqltypes import BigInteger, Integer, String
from sqlmodel import SQLModel

import data.config as config
import data.text as constant_text
from core.logging import bot_logger
from db.models import account_health_db, app_tg_db, apps_db, dump_chat_user_db, user_db, version_state_db


def _cfg(name: str, default: Any = None) -> Any:
    return getattr(config, name, default)


DB_ENGINE = os.getenv("BOT_DB_ENGINE", _cfg("db_http", "postgres"))
DB_NAME = os.getenv("BOT_DB_NAME", _cfg("database_name", _cfg("db", "gemini_message_manager")))
DB_USER = os.getenv("BOT_DB_USER", _cfg("user", "postgres"))
DB_PASSWORD = os.getenv("BOT_DB_PASSWORD", _cfg("password", "postgres"))
DB_HOST = os.getenv("BOT_DB_HOST", _cfg("host", "localhost"))
DB_PORT = os.getenv("BOT_DB_PORT", str(_cfg("port", 5432)))
DB_PATH = os.getenv("BOT_DB_PATH", _cfg("database_path", "data/gemini_message_manager.sqlite3"))
DB_ADMIN_NAME = os.getenv("BOT_DB_ADMIN_NAME", _cfg("database_admin_name", "postgres"))


def _normalize_engine_name(engine: str) -> str:
    value = (engine or "").lower().strip()
    if value in {"postgres", "postgresql", "psql", "postgresql+asyncpg"}:
        return "postgresql+asyncpg"
    if value in {"sqlite", "sqlite+aiosqlite"}:
        return "sqlite+aiosqlite"
    return value


def _build_connection_string() -> str:
    engine = _normalize_engine_name(DB_ENGINE)
    if engine == "sqlite+aiosqlite":
        return f"{engine}:///{DB_PATH}"
    return f"{engine}://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"


DB_CONNECTION_STRING = _build_connection_string()
admin_id_list = list(_cfg("admin_id_list", []) or [])

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quote_ident(name: str) -> str:
    if not _IDENT_RE.fullmatch(name):
        raise ValueError(f"Unsafe SQL identifier: {name}")
    return f'"{name}"'


def _to_uuid(value: Any) -> Optional[UUID]:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _normalize_timezone_offset(offset: Any, default: int = 3) -> int:
    try:
        value = int(offset)
    except (TypeError, ValueError):
        value = default
    return max(-12, min(14, value))
def _inspect_columns(sync_conn, table_name: str) -> dict[str, Any]:
    inspector = inspect(sync_conn)
    columns = inspector.get_columns(table_name, schema="public")
    return {col["name"]: col["type"] for col in columns}


async def _ensure_postgres_database_exists() -> None:
    if _normalize_engine_name(DB_ENGINE) != "postgresql+asyncpg":
        return

    connection = None
    admin_db_candidates = [DB_ADMIN_NAME, "postgres", "template1"]

    for admin_db in admin_db_candidates:
        try:
            connection = await asyncpg.connect(
                user=DB_USER,
                password=DB_PASSWORD,
                host=DB_HOST,
                port=int(DB_PORT),
                database=admin_db,
            )
            break
        except Exception:
            connection = None

    if connection is None:
        raise RuntimeError("Cannot connect to PostgreSQL admin database to ensure target database exists")

    try:
        exists = await connection.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", DB_NAME)
        if not exists:
            safe_db_name = DB_NAME.replace('"', '""')
            await connection.execute(f'CREATE DATABASE "{safe_db_name}"')
            bot_logger.info(f"Database '{DB_NAME}' created")
    finally:
        await connection.close()


async def _init_schema() -> None:
    if _engine is None:
        return

    async with _engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def _sync_missing_columns_postgres() -> None:
    if _engine is None or _normalize_engine_name(DB_ENGINE) != "postgresql+asyncpg":
        return

    dialect = _engine.sync_engine.dialect

    async with _engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            existing_columns = await conn.run_sync(lambda sync_conn: _inspect_columns(sync_conn, table.name))

            for column in table.columns:
                if column.name in existing_columns:
                    continue

                column_type = column.type.compile(dialect=dialect)

                default_sql = ""
                if column.default is not None and getattr(column.default, "is_scalar", False):
                    default_value = column.default.arg
                    if isinstance(default_value, str):
                        escaped = default_value.replace("'", "''")
                        default_sql = f" DEFAULT '{escaped}'"
                    elif isinstance(default_value, bool):
                        default_sql = f" DEFAULT {'TRUE' if default_value else 'FALSE'}"
                    elif default_value is not None:
                        default_sql = f" DEFAULT {default_value}"

                not_null_sql = " NOT NULL" if (not column.nullable and default_sql) else ""
                table_sql = _quote_ident(table.name)
                column_sql = _quote_ident(column.name)

                await conn.execute(
                    text(
                        f"ALTER TABLE {table_sql} ADD COLUMN {column_sql} "
                        f"{column_type}{default_sql}{not_null_sql}"
                    )
                )
                bot_logger.info(f"Applied schema update: {table.name}.{column.name}")


async def _sync_bigint_columns_postgres() -> None:
    if _engine is None or _normalize_engine_name(DB_ENGINE) != "postgresql+asyncpg":
        return

    bigint_columns = {
        "username_history_db": ["user_id", "date"],
        "user_db": ["user_id", "gemini_proxy_checked_at", "update_snooze_until", "update_last_notified"],
        "app_tg_db": ["user_id", "app_id"],
        "apps_db": [
            "admin_id",
            "user_id",
            "alert_black_list_id",
            "alert_del_chat_id",
            "alert_new_chat_id",
            "last_update",
        ],
        "history_users_db": ["admin_id", "user_id", "date"],
        "dump_chat_user_db": ["admin_id", "chat_id"],
        "account_health_db": ["admin_id", "user_id", "date"],
        "version_state_db": ["checked_at"],
    }

    async with _engine.begin() as conn:
        for table_name, columns in bigint_columns.items():
            column_types = await conn.run_sync(lambda sync_conn: _inspect_columns(sync_conn, table_name))
            for column_name in columns:
                current_type = column_types.get(column_name)
                if isinstance(current_type, Integer) and not isinstance(current_type, BigInteger):
                    table_sql = _quote_ident(table_name)
                    column_sql = _quote_ident(column_name)

                    await conn.execute(
                        text(
                            f"ALTER TABLE {table_sql} "
                            f"ALTER COLUMN {column_sql} TYPE BIGINT "
                            f"USING {column_sql}::bigint"
                        )
                    )
                    bot_logger.info(f"Applied bigint migration: {table_name}.{column_name}")



async def _sync_uuid_columns_postgres() -> None:
    if _engine is None or _normalize_engine_name(DB_ENGINE) != "postgresql+asyncpg":
        return

    uuid_columns = {
        "username_history_db": ["uuid"],
        "user_db": ["uuid"],
        "app_tg_db": ["uuid"],
        "apps_db": ["uuid", "app_tg"],
        "history_users_db": ["uuid"],
        "dump_chat_user_db": ["uuid"],
        "account_health_db": ["uuid", "account_uuid"],
    }

    async with _engine.begin() as conn:
        for table_name, columns in uuid_columns.items():
            table = SQLModel.metadata.tables.get(table_name)
            if table is None:
                continue

            column_types = await conn.run_sync(lambda sync_conn: _inspect_columns(sync_conn, table_name))
            for column_name in columns:
                current_type = column_types.get(column_name)
                if current_type is None or isinstance(current_type, PGUUID):
                    continue

                # Convert legacy varchar UUID columns to native Postgres UUID.
                if isinstance(current_type, String):
                    table_sql = _quote_ident(table_name)
                    column_sql = _quote_ident(column_name)
                    nullable = bool(table.columns[column_name].nullable)

                    if nullable:
                        using_expr = (
                            f"CASE "
                            f"WHEN {column_sql} IS NULL THEN NULL "
                            f"WHEN {column_sql}::text = '' THEN NULL "
                            f"ELSE {column_sql}::uuid END"
                        )
                    else:
                        using_expr = f"{column_sql}::uuid"

                    await conn.execute(
                        text(
                            f"ALTER TABLE {table_sql} "
                            f"ALTER COLUMN {column_sql} TYPE UUID "
                            f"USING {using_expr}"
                        )
                    )
                    bot_logger.info(f"Applied uuid migration: {table_name}.{column_name}")


async def _apply_compat_migrations() -> None:
    if _engine is None:
        return

    await _sync_missing_columns_postgres()
    await _sync_bigint_columns_postgres()
    await _sync_uuid_columns_postgres()


async def connect_database() -> None:
    global _engine, _session_factory

    if _engine is not None:
        return

    await _ensure_postgres_database_exists()

    _engine = create_async_engine(
        DB_CONNECTION_STRING,
        echo=False,
        pool_pre_ping=True,
        future=True,
    )
    _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)

    await _init_schema()
    await _apply_compat_migrations()


async def close_database() -> None:
    global _engine, _session_factory

    if _engine is not None:
        await _engine.dispose()

    _engine = None
    _session_factory = None


@asynccontextmanager
async def _session_scope() -> AsyncIterator[AsyncSession]:
    if _session_factory is None:
        await connect_database()

    assert _session_factory is not None
    async with _session_factory() as session:
        yield session




async def get_version_state_cache(default_state: str = constant_text.VERSION_STATE_UNKNOWN) -> tuple[str, int, str | None]:
    async with _session_scope() as session:
        result = await session.execute(select(version_state_db).where(version_state_db.id == 1))
        state_row = result.scalars().first()
        if not state_row:
            return default_state, 0, None

        state = str(getattr(state_row, "state", default_state) or default_state)
        checked_at = int(getattr(state_row, "checked_at", 0) or 0)
        remote_version = getattr(state_row, "remote_version", None)
        return state, checked_at, remote_version


async def set_version_state_cache(
    local_version: str,
    remote_version: str | None,
    state: str,
    checked_at: int | None = None,
) -> int:
    checked_at_value = int(checked_at if checked_at is not None else time.time())

    async with _session_scope() as session:
        result = await session.execute(select(version_state_db).where(version_state_db.id == 1))
        state_row = result.scalars().first()

        if not state_row:
            state_row = version_state_db(
                id=1,
                local_version=str(local_version),
                remote_version=str(remote_version) if remote_version else None,
                state=str(state),
                checked_at=checked_at_value,
            )
        else:
            state_row.local_version = str(local_version)
            state_row.remote_version = str(remote_version) if remote_version else None
            state_row.state = str(state)
            state_row.checked_at = checked_at_value

        session.add(state_row)
        await session.commit()

    return checked_at_value

async def get_user(user_id):
    async with _session_scope() as session:
        result = await session.execute(select(user_db).where(user_db.user_id == user_id))
        return result.scalars().first()



async def get_user_timezone_offset(user_id: int, default: int = 3) -> int:
    async with _session_scope() as session:
        result = await session.execute(select(user_db).where(user_db.user_id == int(user_id)))
        user = result.scalars().first()
        if not user:
            return _normalize_timezone_offset(default)
        return _normalize_timezone_offset(getattr(user, "timezone_offset", default), default)


async def set_user_timezone_offset(user_id: int, offset: int) -> int:
    offset_value = _normalize_timezone_offset(offset)

    async with _session_scope() as session:
        result = await session.execute(select(user_db).where(user_db.user_id == int(user_id)))
        user = result.scalars().first()

        if not user:
            roles = "admin" if int(user_id) in admin_id_list else None
            user = user_db(user_id=int(user_id), roles=roles, timezone_offset=offset_value)
            session.add(user)
        else:
            user.timezone_offset = offset_value
            session.add(user)

        await session.commit()

    return offset_value


async def get_user_auto_update_enabled(user_id: int, default: int = 0) -> int:
    async with _session_scope() as session:
        result = await session.execute(select(user_db).where(user_db.user_id == int(user_id)))
        user = result.scalars().first()
        if not user:
            return int(default)
        return int(getattr(user, "auto_update_enabled", default) or 0)


async def set_user_auto_update_enabled(user_id: int, enabled: int) -> int:
    enabled_value = 1 if int(enabled) else 0

    async with _session_scope() as session:
        result = await session.execute(select(user_db).where(user_db.user_id == int(user_id)))
        user = result.scalars().first()

        if not user:
            roles = "admin" if int(user_id) in admin_id_list else None
            user = user_db(user_id=int(user_id), roles=roles, auto_update_enabled=enabled_value, timezone_offset=3)
        else:
            user.auto_update_enabled = enabled_value

        session.add(user)
        await session.commit()

    return enabled_value


async def get_user_update_notification_state(user_id: int) -> tuple[int, int]:
    async with _session_scope() as session:
        result = await session.execute(select(user_db).where(user_db.user_id == int(user_id)))
        user = result.scalars().first()
        if not user:
            return 0, 0

        snooze_until = int(getattr(user, "update_snooze_until", 0) or 0)
        last_notified = int(getattr(user, "update_last_notified", 0) or 0)
        return snooze_until, last_notified


async def set_user_update_snooze_until(user_id: int, until_ts: int) -> int:
    value = int(until_ts)

    async with _session_scope() as session:
        result = await session.execute(select(user_db).where(user_db.user_id == int(user_id)))
        user = result.scalars().first()

        if not user:
            roles = "admin" if int(user_id) in admin_id_list else None
            user = user_db(user_id=int(user_id), roles=roles, update_snooze_until=value, timezone_offset=3)
        else:
            user.update_snooze_until = value

        session.add(user)
        await session.commit()

    return value


async def set_user_update_last_notified(user_id: int, ts_value: int) -> int:
    value = int(ts_value)

    async with _session_scope() as session:
        result = await session.execute(select(user_db).where(user_db.user_id == int(user_id)))
        user = result.scalars().first()

        if not user:
            roles = "admin" if int(user_id) in admin_id_list else None
            user = user_db(user_id=int(user_id), roles=roles, update_last_notified=value, timezone_offset=3)
        else:
            user.update_last_notified = value

        session.add(user)
        await session.commit()

    return value

async def update_user(user_id, username, full_name):
    async with _session_scope() as session:
        result = await session.execute(select(user_db).where(user_db.user_id == user_id))
        temp = result.scalars().first()

        roles = "admin" if user_id in admin_id_list else None

        if not temp:
            temp = user_db(user_id=user_id, roles=roles, timezone_offset=3)
            session.add(temp)

        if temp.roles != roles or temp.username != username or temp.full_name != full_name:
            temp.username = username
            temp.full_name = full_name
            temp.roles = roles

        if getattr(temp, "timezone_offset", None) is None:
            temp.timezone_offset = 3

        await session.commit()


async def delete_user(user_id):
    async with _session_scope() as session:
        result = await session.execute(select(user_db).where(user_db.user_id == user_id))
        temp = result.scalars().first()
        if temp:
            await session.delete(temp)
            await session.commit()


async def get_admins():
    async with _session_scope() as session:
        result = await session.execute(select(user_db).where(user_db.roles == "admin"))
        return result.scalars().all()


async def get_app_tg_user_id(user_id, offset=0):
    async with _session_scope() as session:
        result = await session.execute(
            select(app_tg_db).where(app_tg_db.user_id == user_id).offset(offset).limit(5)
        )
        count_result = await session.execute(
            select(func.count()).select_from(app_tg_db).where(app_tg_db.user_id == user_id)
        )
        return result.scalars().all(), int(count_result.scalar() or 0)


async def get_app_tg_uuid(uuid, user_id):
    uuid_value = _to_uuid(uuid)
    if uuid_value is None:
        return None

    async with _session_scope() as session:
        result = await session.execute(
            select(app_tg_db).where(app_tg_db.uuid == uuid_value, app_tg_db.user_id == user_id)
        )
        return result.scalars().first()


async def get_app_tg_uuid_aio(uuid):
    uuid_value = _to_uuid(uuid)
    if uuid_value is None:
        return None

    async with _session_scope() as session:
        result = await session.execute(select(app_tg_db).where(app_tg_db.uuid == uuid_value))
        return result.scalars().first()



async def get_accounts_count_by_app_tg_uuid(app_tg_uuid) -> int:
    uuid_value = _to_uuid(app_tg_uuid)
    if uuid_value is None:
        return 0

    async with _session_scope() as session:
        result = await session.execute(
            select(func.count()).select_from(apps_db).where(apps_db.app_tg == uuid_value)
        )
        return int(result.scalar() or 0)
async def del_app_tg_uuid(uuid, user_id):
    uuid_value = _to_uuid(uuid)
    if uuid_value is None:
        return False

    async with _session_scope() as session:
        result = await session.execute(
            select(app_tg_db).where(app_tg_db.uuid == uuid_value, app_tg_db.user_id == user_id)
        )
        temp = result.scalars().first()
        if not temp:
            return False

        await session.delete(temp)
        await session.commit()
        return True


async def get_app_tg_to_params_all(user_id, app_id, api_hash):
    async with _session_scope() as session:
        result = await session.execute(
            select(app_tg_db).where(
                app_tg_db.user_id == user_id,
                app_tg_db.app_id == app_id,
                app_tg_db.api_hash == api_hash,
            )
        )
        return result.scalars().first()


async def create_app_tg(user_id, app_id, api_hash, tag_name):
    async with _session_scope() as session:
        session.add(
            app_tg_db(
                user_id=user_id,
                app_id=app_id,
                api_hash=api_hash,
                tag_name=tag_name,
            )
        )
        await session.commit()


async def get_account_user_id(admin_id, offset=0):
    async with _session_scope() as session:
        result = await session.execute(
            select(apps_db).where(apps_db.admin_id == admin_id).offset(offset).limit(5)
        )
        count_result = await session.execute(
            select(func.count()).select_from(apps_db).where(apps_db.admin_id == admin_id)
        )
        return result.scalars().all(), int(count_result.scalar() or 0)


async def get_account_all(active_only=False):
    async with _session_scope() as session:
        query = select(apps_db)
        if active_only:
            query = query.where(apps_db.is_active == 1)
        result = await session.execute(query)
        return result.scalars().all()


async def get_account_tg_to_user_id(user_id, admin_id=None):
    async with _session_scope() as session:
        query = select(apps_db).where(apps_db.user_id == user_id)
        if admin_id is not None:
            query = query.where(apps_db.admin_id == admin_id)

        result = await session.execute(query)
        return result.scalars().first()


async def get_account_uuid(uuid, admin_id):
    uuid_value = _to_uuid(uuid)
    if uuid_value is None:
        return None

    async with _session_scope() as session:
        result = await session.execute(
            select(apps_db).where(apps_db.uuid == uuid_value, apps_db.admin_id == admin_id)
        )
        return result.scalars().first()


async def del_account_uuid(uuid, admin_id):
    uuid_value = _to_uuid(uuid)
    if uuid_value is None:
        return False

    async with _session_scope() as session:
        result = await session.execute(
            select(apps_db).where(apps_db.uuid == uuid_value, apps_db.admin_id == admin_id)
        )
        temp = result.scalars().first()
        if not temp:
            return False

        await session.delete(temp)
        await session.commit()
        return True


async def update_account_uuid(uuid, admin_id, **fields):
    uuid_value = _to_uuid(uuid)
    if uuid_value is None:
        return None

    async with _session_scope() as session:
        result = await session.execute(
            select(apps_db).where(apps_db.uuid == uuid_value, apps_db.admin_id == admin_id)
        )
        temp = result.scalars().first()
        if not temp:
            return None

        for key, value in fields.items():
            if hasattr(temp, key):
                setattr(temp, key, value)

        session.add(temp)
        await session.commit()
        await session.refresh(temp)
        return temp


async def create_account_tg(admin_id, user_id, app_tg, number):
    app_tg_uuid = _to_uuid(app_tg)
    if app_tg_uuid is None:
        return None

    async with _session_scope() as session:
        result = await session.execute(
            select(apps_db).where(apps_db.admin_id == admin_id, apps_db.user_id == user_id)
        )
        account = result.scalars().first()

        if account:
            account.app_tg = app_tg_uuid
            account.number = number
            account.is_active = 1
            if getattr(account, "alert_spoiler_media", None) is None:
                account.alert_spoiler_media = 1
            session.add(account)
            await session.commit()
            await session.refresh(account)
            return account

        account = apps_db(
            admin_id=admin_id,
            user_id=user_id,
            app_tg=app_tg_uuid,
            number=number,
            alert_del_chat_id=admin_id,
            alert_new_chat_id=admin_id,
            alert_bot=0,
            alert_spoiler_media=1,
            is_active=1,
        )
        session.add(account)
        await session.commit()
        await session.refresh(account)
        return account


async def get_dump_chat_admin_all(admin_id):
    async with _session_scope() as session:
        result = await session.execute(select(dump_chat_user_db).where(dump_chat_user_db.admin_id == admin_id))
        return result.scalars().all()


async def get_dump_chat_user(admin_id, chat_id):
    async with _session_scope() as session:
        result = await session.execute(
            select(dump_chat_user_db).where(
                dump_chat_user_db.admin_id == admin_id,
                dump_chat_user_db.chat_id == chat_id,
            )
        )
        return result.scalars().first()


async def del_dump_chat_user(admin_id, chat_id):
    async with _session_scope() as session:
        result = await session.execute(
            select(dump_chat_user_db).where(
                dump_chat_user_db.admin_id == admin_id,
                dump_chat_user_db.chat_id == chat_id,
            )
        )
        records = result.scalars().all()
        if not records:
            return False

        for item in records:
            await session.delete(item)

        await session.commit()
        return True


async def create_dump_chat_user(admin_id, chat_id):
    async with _session_scope() as session:
        exists = await session.execute(
            select(dump_chat_user_db).where(
                dump_chat_user_db.admin_id == admin_id,
                dump_chat_user_db.chat_id == chat_id,
            )
        )
        if exists.scalars().first():
            return False

        session.add(dump_chat_user_db(admin_id=admin_id, chat_id=chat_id))
        await session.commit()
        return True


async def get_account_by_number(number):
    async with _session_scope() as session:
        result = await session.execute(select(apps_db).where(apps_db.number == str(number)))
        return result.scalars().first()


async def delete_account_by_number(number):
    async with _session_scope() as session:
        result = await session.execute(select(apps_db).where(apps_db.number == str(number)))
        records = result.scalars().all()
        if not records:
            return None

        account = records[0]
        for item in records:
            await session.delete(item)

        await session.commit()
        return account


async def delete_dump_chat_admin_all(admin_id):
    async with _session_scope() as session:
        result = await session.execute(select(dump_chat_user_db).where(dump_chat_user_db.admin_id == admin_id))
        records = result.scalars().all()
        if not records:
            return 0

        for item in records:
            await session.delete(item)

        await session.commit()
        return len(records)





async def add_account_health_event(account_uuid, admin_id, user_id, status, date=None, reason=None):
    async with _session_scope() as session:
        session.add(
            account_health_db(
                account_uuid=_to_uuid(account_uuid),
                admin_id=int(admin_id) if admin_id is not None else 0,
                user_id=int(user_id) if user_id is not None else 0,
                status=int(status),
                date=int(date) if date is not None else int(time.time()),
                reason=reason,
            )
        )
        await session.commit()


async def get_account_health_events(account_uuid, since_ts):
    async with _session_scope() as session:
        result = await session.execute(
            select(account_health_db).where(
                account_health_db.account_uuid == _to_uuid(account_uuid),
                account_health_db.date >= int(since_ts),
            )
        )
        return result.scalars().all()


async def get_admin_health_events(admin_id, since_ts):
    async with _session_scope() as session:
        result = await session.execute(
            select(account_health_db).where(
                account_health_db.admin_id == int(admin_id),
                account_health_db.date >= int(since_ts),
            )
        )
        return result.scalars().all()


async def get_accounts_overview(admin_id):
    async with _session_scope() as session:
        own_total_q = await session.execute(select(func.count()).select_from(apps_db).where(apps_db.admin_id == admin_id))
        own_active_q = await session.execute(
            select(func.count()).select_from(apps_db).where(apps_db.admin_id == admin_id, apps_db.is_active == 1)
        )
        all_total_q = await session.execute(select(func.count()).select_from(apps_db))
        all_active_q = await session.execute(select(func.count()).select_from(apps_db).where(apps_db.is_active == 1))

        return {
            "own_total": int(own_total_q.scalar() or 0),
            "own_active": int(own_active_q.scalar() or 0),
            "all_total": int(all_total_q.scalar() or 0),
            "all_active": int(all_active_q.scalar() or 0),
        }








async def get_all_health_events(since_ts):
    async with _session_scope() as session:
        result = await session.execute(
            select(account_health_db).where(
                account_health_db.date >= int(since_ts),
            )
        )
        return result.scalars().all()






















async def _ensure_user_row_for_settings(user_id: int) -> user_db:
    async with _session_scope() as session:
        result = await session.execute(select(user_db).where(user_db.user_id == int(user_id)))
        user = result.scalars().first()

        if not user:
            roles = "admin" if int(user_id) in admin_id_list else None
            user = user_db(user_id=int(user_id), roles=roles, timezone_offset=3)
            session.add(user)
            await session.commit()
            await session.refresh(user)

        return user


async def get_user_gemini_proxy_config(user_id: int) -> dict[str, Any]:
    async with _session_scope() as session:
        result = await session.execute(select(user_db).where(user_db.user_id == int(user_id)))
        user = result.scalars().first()

        if not user:
            return {
                "proxy": None,
                "enabled": 0,
                "status": 0,
                "checked_at": 0,
                "last_error": None,
            }

        return {
            "proxy": (user.gemini_proxy or "").strip() or None,
            "enabled": int(getattr(user, "gemini_proxy_enabled", 0) or 0),
            "status": int(getattr(user, "gemini_proxy_status", 0) or 0),
            "checked_at": int(getattr(user, "gemini_proxy_checked_at", 0) or 0),
            "last_error": (getattr(user, "gemini_proxy_last_error", None) or None),
        }


async def set_user_gemini_proxy(user_id: int, proxy_value: str) -> dict[str, Any]:
    proxy_clean = (proxy_value or "").strip()

    async with _session_scope() as session:
        result = await session.execute(select(user_db).where(user_db.user_id == int(user_id)))
        user = result.scalars().first()

        if not user:
            roles = "admin" if int(user_id) in admin_id_list else None
            user = user_db(user_id=int(user_id), roles=roles, timezone_offset=3)

        user.gemini_proxy = proxy_clean
        user.gemini_proxy_enabled = 1
        user.gemini_proxy_status = 0
        user.gemini_proxy_checked_at = int(time.time())
        user.gemini_proxy_last_error = None

        session.add(user)
        await session.commit()
        await session.refresh(user)

        return {
            "proxy": user.gemini_proxy,
            "enabled": int(user.gemini_proxy_enabled or 0),
            "status": int(user.gemini_proxy_status or 0),
            "checked_at": int(user.gemini_proxy_checked_at or 0),
            "last_error": user.gemini_proxy_last_error,
        }


async def disable_user_gemini_proxy(user_id: int, reason: str | None = None) -> dict[str, Any]:
    async with _session_scope() as session:
        result = await session.execute(select(user_db).where(user_db.user_id == int(user_id)))
        user = result.scalars().first()

        if not user:
            roles = "admin" if int(user_id) in admin_id_list else None
            user = user_db(user_id=int(user_id), roles=roles, timezone_offset=3)

        user.gemini_proxy_enabled = 0
        user.gemini_proxy_status = 0
        user.gemini_proxy_checked_at = int(time.time())
        user.gemini_proxy_last_error = (reason or None)

        session.add(user)
        await session.commit()
        await session.refresh(user)

        return {
            "proxy": (user.gemini_proxy or "").strip() or None,
            "enabled": int(user.gemini_proxy_enabled or 0),
            "status": int(user.gemini_proxy_status or 0),
            "checked_at": int(user.gemini_proxy_checked_at or 0),
            "last_error": user.gemini_proxy_last_error,
        }


async def set_user_gemini_proxy_health(user_id: int, is_ok: bool, error: str | None = None) -> dict[str, Any]:
    async with _session_scope() as session:
        result = await session.execute(select(user_db).where(user_db.user_id == int(user_id)))
        user = result.scalars().first()

        if not user:
            roles = "admin" if int(user_id) in admin_id_list else None
            user = user_db(user_id=int(user_id), roles=roles, timezone_offset=3)

        user.gemini_proxy_status = 1 if is_ok else 0
        user.gemini_proxy_checked_at = int(time.time())
        user.gemini_proxy_last_error = None if is_ok else (error or "proxy_check_failed")

        session.add(user)
        await session.commit()
        await session.refresh(user)

        return {
            "proxy": (user.gemini_proxy or "").strip() or None,
            "enabled": int(user.gemini_proxy_enabled or 0),
            "status": int(user.gemini_proxy_status or 0),
            "checked_at": int(user.gemini_proxy_checked_at or 0),
            "last_error": user.gemini_proxy_last_error,
        }


async def get_latest_admin_health_event(admin_id: int):
    async with _session_scope() as session:
        result = await session.execute(
            select(account_health_db)
            .where(account_health_db.admin_id == int(admin_id))
            .order_by(account_health_db.date.desc())
            .limit(1)
        )
        return result.scalars().first()


