"""Persistent encrypted attachment downloads, independent of Telegram delivery."""
from alembic import op
import sqlalchemy as sa

revision = "20261103_03"
down_revision = "20261103_02"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("message_attachment",
        sa.Column("uuid", sa.Uuid(), primary_key=True),
        sa.Column("revision_uuid", sa.Uuid(), sa.ForeignKey("message_revision.uuid"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("file_key", sa.String(), nullable=False),
        sa.Column("sources", sa.String(), nullable=False),
        sa.Column("expected_size", sa.BigInteger()),
        sa.Column("blob_key", sa.String()), sa.Column("stored_size", sa.BigInteger()),
        sa.Column("status", sa.String(), nullable=False), sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.BigInteger(), nullable=False),
        sa.Column("lease_token", sa.Uuid()), sa.Column("lease_until", sa.BigInteger(), nullable=False),
        sa.Column("last_error", sa.String()),
        sa.UniqueConstraint("revision_uuid", "position", name="uq_attachment_revision_position"))
    for column in ("revision_uuid", "owner_id", "file_key", "status"):
        op.create_index(f"ix_message_attachment_{column}", "message_attachment", [column])


def downgrade():
    op.drop_table("message_attachment")
