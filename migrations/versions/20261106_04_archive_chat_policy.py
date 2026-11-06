"""Remember archive chat types and progress through available avatar history."""
from alembic import op
import sqlalchemy as sa

revision = "20261106_04"
down_revision = "20261106_03"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("archive_chat_policy",
        sa.Column("account_user_id", sa.BigInteger(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("retry_at", sa.BigInteger(), nullable=False, server_default="0"))
    op.create_index("ix_archive_chat_policy_chat_id", "archive_chat_policy", ["chat_id"])
    op.create_table("avatar_history_scan",
        sa.Column("owner_id", sa.BigInteger(), primary_key=True),
        sa.Column("account_user_id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), primary_key=True),
        sa.Column("head_key", sa.String(), nullable=False),
        sa.Column("next_limit", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("next_attempt_at", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("lease_token", sa.Uuid()))


def downgrade():
    op.drop_table("avatar_history_scan")
    op.drop_table("archive_chat_policy")
