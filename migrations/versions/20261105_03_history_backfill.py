"""Durable bounded private-chat history and Telegram cooldowns."""
from alembic import op
import sqlalchemy as sa

revision = "20261105_03"
down_revision = "20261105_02"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("history_run",
        sa.Column("account_uuid", sa.Uuid(), primary_key=True),
        sa.Column("account_user_id", sa.BigInteger(), nullable=False),
        sa.Column("next_run_at", sa.BigInteger(), nullable=False))
    op.create_index("ix_history_run_account_user_id", "history_run", ["account_user_id"])
    op.create_table("history_chat",
        sa.Column("account_uuid", sa.Uuid(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), primary_key=True),
        sa.Column("known_top_id", sa.Integer(), nullable=False),
        sa.Column("oldest_message_id", sa.Integer(), nullable=True),
        sa.Column("reached_start", sa.Boolean(), nullable=False),
        sa.Column("excluded", sa.Boolean(), nullable=False),
        sa.Column("turn", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.BigInteger(), nullable=False),
        sa.Column("last_head_at", sa.BigInteger(), nullable=False),
        sa.Column("retry_at", sa.BigInteger(), nullable=False),
        sa.Column("last_error", sa.String(), nullable=True))
    op.create_table("history_range",
        sa.Column("account_uuid", sa.Uuid(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), primary_key=True),
        sa.Column("low_id", sa.Integer(), primary_key=True),
        sa.Column("high_id", sa.Integer(), nullable=False))
    op.create_table("telegram_cooldown",
        sa.Column("account_user_id", sa.BigInteger(), primary_key=True),
        sa.Column("blocked_until", sa.BigInteger(), nullable=False),
        sa.Column("media_next_at", sa.BigInteger(), nullable=False))
    op.add_column("stored_message", sa.Column("history_missing_at", sa.BigInteger(), nullable=True))


def downgrade():
    op.drop_column("stored_message", "history_missing_at")
    op.drop_table("telegram_cooldown")
    op.drop_table("history_range")
    op.drop_table("history_chat")
    op.drop_index("ix_history_run_account_user_id", table_name="history_run")
    op.drop_table("history_run")
