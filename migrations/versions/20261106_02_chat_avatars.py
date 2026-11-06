"""Owner-scoped encrypted avatar cache and durable download queue."""
from alembic import op
import sqlalchemy as sa

revision = "20261106_02"
down_revision = "20261106_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("chat_avatar",
        sa.Column("uuid", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("account_user_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("photo_key", sa.String(), nullable=False),
        sa.Column("file_id", sa.String()), sa.Column("source", sa.String(), nullable=False),
        sa.Column("blob_key", sa.String()), sa.Column("status", sa.String(), nullable=False),
        sa.Column("next_attempt_at", sa.BigInteger(), nullable=False),
        sa.Column("lease_until", sa.BigInteger(), nullable=False), sa.Column("lease_token", sa.Uuid()),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("owner_id", "account_user_id", "user_id", name="uq_chat_avatar_peer"))
    op.create_index("ix_chat_avatar_owner_id", "chat_avatar", ["owner_id"])
    op.create_index("ix_chat_avatar_account_user_id", "chat_avatar", ["account_user_id"])


def downgrade():
    op.drop_table("chat_avatar")
