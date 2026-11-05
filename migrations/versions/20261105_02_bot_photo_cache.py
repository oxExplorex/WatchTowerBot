"""Cache reusable Telegram photo IDs separately for each bot and asset version."""
from alembic import op
import sqlalchemy as sa

revision = "20261105_02"
down_revision = "20261105_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("bot_photo_cache",
        sa.Column("bot_id", sa.BigInteger(), primary_key=True),
        sa.Column("image_hash", sa.String(), primary_key=True),
        sa.Column("file_id", sa.String(), nullable=False))


def downgrade():
    op.drop_table("bot_photo_cache")
