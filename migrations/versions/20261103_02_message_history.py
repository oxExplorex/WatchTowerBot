"""Store encrypted messages and observed revisions from both Telegram transports."""
from alembic import op
import sqlalchemy as sa

revision = "20261103_02"
down_revision = "20261103_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("stored_message",
        sa.Column("uuid", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("account_user_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_namespace", sa.Boolean(), nullable=False),
        sa.Column("sender_id", sa.BigInteger()), sa.Column("sent_at", sa.BigInteger()),
        sa.Column("first_seen_at", sa.BigInteger(), nullable=False),
        sa.Column("original_seen", sa.Boolean(), nullable=False),
        sa.Column("is_edited", sa.Boolean(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_observed_at", sa.BigInteger()),
        sa.Column("latest_revision_uuid", sa.Uuid()), sa.Column("latest_version_at", sa.BigInteger()),
        sa.UniqueConstraint("owner_id", "account_user_id", "chat_id", "message_id", name="uq_stored_message_identity"))
    for column in ("owner_id", "account_user_id", "chat_id", "message_id"):
        op.create_index(f"ix_stored_message_{column}", "stored_message", [column])
    op.create_table("message_revision",
        sa.Column("uuid", sa.Uuid(), primary_key=True),
        sa.Column("message_uuid", sa.Uuid(), sa.ForeignKey("stored_message.uuid"), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("version_at", sa.BigInteger(), nullable=False),
        sa.Column("observed_at", sa.BigInteger(), nullable=False),
        sa.Column("payload", sa.String(), nullable=False),
        sa.Column("fingerprint", sa.String(), nullable=False),
        sa.Column("encryption_version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("message_uuid", "revision_no", name="uq_message_revision_number"))
    for column in ("message_uuid", "fingerprint"):
        op.create_index(f"ix_message_revision_{column}", "message_revision", [column])
    op.create_table("message_receipt",
        sa.Column("uuid", sa.Uuid(), primary_key=True),
        sa.Column("message_uuid", sa.Uuid(), sa.ForeignKey("stored_message.uuid"), nullable=False),
        sa.Column("revision_uuid", sa.Uuid(), sa.ForeignKey("message_revision.uuid")),
        sa.Column("source", sa.String(), nullable=False), sa.Column("event_key", sa.String(), nullable=False),
        sa.UniqueConstraint("message_uuid", "source", "event_key", name="uq_message_receipt_event"))
    for column in ("message_uuid", "revision_uuid"):
        op.create_index(f"ix_message_receipt_{column}", "message_receipt", [column])
    op.create_table("pending_message_deletion",
        sa.Column("uuid", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("account_user_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("observed_at", sa.BigInteger(), nullable=False),
        sa.Column("resolved_message_uuid", sa.Uuid(), sa.ForeignKey("stored_message.uuid")),
        sa.UniqueConstraint("owner_id", "account_user_id", "message_id", name="uq_pending_message_deletion"))
    for column in ("account_user_id", "message_id"):
        op.create_index(f"ix_pending_message_deletion_{column}", "pending_message_deletion", [column])


def downgrade():
    op.drop_table("pending_message_deletion")
    op.drop_table("message_receipt")
    op.drop_table("message_revision")
    op.drop_table("stored_message")
