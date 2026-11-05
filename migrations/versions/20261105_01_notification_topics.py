"""Persist private-chat notification topics and daily reminders."""
from alembic import op
import sqlalchemy as sa

revision = "20261105_01"
down_revision = "20261104_03"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("notification_topic",
        sa.Column("bot_id", sa.BigInteger(), primary_key=True),
        sa.Column("owner_id", sa.BigInteger(), primary_key=True),
        sa.Column("topic_key", sa.String(), primary_key=True),
        sa.Column("thread_id", sa.BigInteger(), nullable=False))
    op.create_table("topic_reminder",
        sa.Column("bot_id", sa.BigInteger(), primary_key=True),
        sa.Column("owner_id", sa.BigInteger(), primary_key=True),
        sa.Column("next_at", sa.BigInteger(), nullable=False))


def downgrade():
    op.drop_table("topic_reminder")
    op.drop_table("notification_topic")
