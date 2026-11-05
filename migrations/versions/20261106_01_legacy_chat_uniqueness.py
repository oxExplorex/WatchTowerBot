"""Repair chat membership uniqueness skipped when a legacy database was stamped."""
from alembic import op
import sqlalchemy as sa

revision = "20261106_01"
down_revision = "20261105_04"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    table = "dump_chat_user_db"
    keys = {"admin_id", "chat_id"}
    unique = inspector.get_unique_constraints(table) + [
        item for item in inspector.get_indexes(table) if item.get("unique") and not any(
            key.endswith("_where") and value is not None for key, value in item.get("dialect_options", {}).items())
    ]
    if any(set(item["column_names"]) == keys for item in unique):
        return
    # Preserve every duplicate row before consolidating this membership set.
    # No message, revision, attachment or chat-history table is modified.
    op.create_table("legacy_dump_chat_duplicates",
        sa.Column("uuid", sa.Uuid(), primary_key=True),
        sa.Column("admin_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False))
    connection.execute(sa.text(
        "INSERT INTO legacy_dump_chat_duplicates (uuid, admin_id, chat_id) "
        "SELECT uuid, admin_id, chat_id FROM (SELECT uuid, admin_id, chat_id, "
        "ROW_NUMBER() OVER (PARTITION BY admin_id, chat_id ORDER BY uuid) AS position "
        "FROM dump_chat_user_db) AS ranked WHERE position > 1"))
    connection.execute(sa.text(
        "DELETE FROM dump_chat_user_db WHERE uuid IN (SELECT uuid FROM legacy_dump_chat_duplicates)"))
    op.create_index("uq_dump_chat_user_db_admin_chat", table, ["admin_id", "chat_id"], unique=True)


def downgrade():
    # The baseline already requires this uniqueness. Keep repaired data and backups.
    pass
