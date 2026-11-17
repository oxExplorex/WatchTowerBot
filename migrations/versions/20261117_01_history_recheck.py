"""Persist the position of bounded rechecks through previously covered history."""
from alembic import op
import sqlalchemy as sa

revision = "20261117_01"
down_revision = "20261106_04"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("history_chat", sa.Column("recheck_before_id", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("history_chat", "recheck_before_id")
