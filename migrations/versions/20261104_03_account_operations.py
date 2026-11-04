"""Persistent account approvals and encrypted transfer staging."""
from alembic import op
import sqlalchemy as sa

revision = "20261104_03"
down_revision = "20261104_02"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("message_attachment", sa.Column("state_version", sa.Integer(), nullable=False, server_default="0"))
    op.create_table("account_operation",
        sa.Column("uuid", sa.Uuid(), primary_key=True),
        sa.Column("account_uuid", sa.Uuid(), nullable=False, index=True),
        sa.Column("account_user_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("owner_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("actor_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, index=True),
        sa.Column("active_account_id", sa.BigInteger(), unique=True),
        sa.Column("target_app_uuid", sa.Uuid()),
        sa.Column("session_number", sa.String()),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.Column("run_token", sa.Uuid()),
        sa.Column("last_error", sa.String()),
        sa.Column("owner_notified", sa.Boolean(), nullable=False),
        sa.Column("result_notified", sa.Boolean(), nullable=False),
        sa.Column("notify_after", sa.BigInteger(), nullable=False))
    op.create_table("account_transfer_revision",
        sa.Column("operation_uuid", sa.Uuid(), sa.ForeignKey("account_operation.uuid"), primary_key=True),
        sa.Column("revision_uuid", sa.Uuid(), primary_key=True),
        sa.Column("original_payload", sa.String(), nullable=False),
        sa.Column("original_version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.String(), nullable=False),
        sa.Column("fingerprint", sa.String(), nullable=False))
    op.create_table("account_transfer_attachment",
        sa.Column("operation_uuid", sa.Uuid(), sa.ForeignKey("account_operation.uuid"), primary_key=True),
        sa.Column("attachment_uuid", sa.Uuid(), primary_key=True),
        sa.Column("original_snapshot", sa.String(), nullable=False),
        sa.Column("original_state_version", sa.Integer(), nullable=False),
        sa.Column("sources", sa.String(), nullable=False),
        sa.Column("file_key", sa.String(), nullable=False),
        sa.Column("blob_key", sa.String()),
        sa.Column("stored_size", sa.BigInteger()),
        sa.Column("encryption_version", sa.Integer(), nullable=False),
        sa.Column("sources_encryption_version", sa.Integer(), nullable=False))
    op.create_table("archive_blob_cleanup",
        sa.Column("owner_id", sa.BigInteger(), primary_key=True),
        sa.Column("blob_key", sa.String(), primary_key=True))


def downgrade():
    raise RuntimeError("Account transfer staging requires a compatible backup to downgrade")
