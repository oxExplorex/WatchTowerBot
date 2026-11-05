from importlib import import_module
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


@pytest.mark.asyncio
async def test_legacy_membership_repair_preserves_duplicates_and_allows_upserts(db_main):
    migration = import_module("migrations.versions.20261106_01_legacy_chat_uniqueness")
    async with db_main.get_session_factory()() as session:
        engine = session.bind

    def check(connection):
        # This entire database is disposable; emulate a stamped old installation.
        current = sa.Table("dump_chat_user_db", sa.MetaData(), autoload_with=connection)
        current.drop(connection)
        table = sa.Table("dump_chat_user_db", sa.MetaData(),
            sa.Column("uuid", sa.Uuid(), primary_key=True),
            sa.Column("admin_id", sa.BigInteger(), nullable=False),
            sa.Column("chat_id", sa.BigInteger(), nullable=False))
        table.create(connection)
        rows = [dict(uuid=uuid4(), admin_id=owner, chat_id=42) for owner in (1001, 1001, 2002)]
        connection.execute(table.insert(), rows)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()  # The repaired schema must also be accepted unchanged.
        backup = sa.Table("legacy_dump_chat_duplicates", sa.MetaData(), autoload_with=connection)
        kept = list(connection.execute(sa.select(table)).mappings())
        copied = list(connection.execute(sa.select(backup)).mappings())
        assert len(kept) == 2 and len(copied) == 1
        assert {UUID(str(row["uuid"])) for row in kept + copied} == {row["uuid"] for row in rows}
        # Use the same dialect-specific ON CONFLICT as message capture.
        from sqlalchemy.dialects import postgresql, sqlite
        insert = postgresql.insert if connection.dialect.name == "postgresql" else sqlite.insert
        result = connection.execute(insert(table).values(uuid=uuid4(), admin_id=1001, chat_id=42)
            .on_conflict_do_nothing(index_elements=["admin_id", "chat_id"]))
        assert result.rowcount == 0

    async with engine.begin() as connection:
        await connection.run_sync(check)
