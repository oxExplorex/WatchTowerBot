"""Retain avatar occurrences and explicit observations without a visible photo."""
from alembic import op
import sqlalchemy as sa

revision = "20261106_03"
down_revision = "20261106_02"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("chat_avatar") as batch:
        batch.add_column(sa.Column("first_seen_at", sa.BigInteger(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("ended_at", sa.BigInteger()))
        batch.drop_constraint("uq_chat_avatar_peer", type_="unique")
    op.execute(sa.text("UPDATE chat_avatar SET first_seen_at = updated_at * 1000000"))
    op.create_index("uq_chat_avatar_current", "chat_avatar", ["owner_id", "account_user_id", "user_id"],
                    unique=True, sqlite_where=sa.text("ended_at IS NULL"), postgresql_where=sa.text("ended_at IS NULL"))


def downgrade():
    # A downgrade would discard history or violate the previous uniqueness rule.
    raise RuntimeError("Avatar history downgrade requires an explicit data-retention decision")
