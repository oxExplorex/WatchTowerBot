"""Index encrypted API hashes without rebuilding application/session tables."""
from alembic import op
import sqlalchemy as sa

revision = "20261104_01"
down_revision = "20261103_04"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("app_tg_db", sa.Column("api_hash_index", sa.String(), nullable=True))
    op.create_index("uq_app_tg_db_user_app_hash_index", "app_tg_db",
                    ["user_id", "app_id", "api_hash_index"], unique=True)
    # Encryption needs the runtime key and runs in the existing startup backfill.
    # Keep the legacy constraint: this avoids a SQLite table rebuild with FK users.


def downgrade():
    op.drop_index("uq_app_tg_db_user_app_hash_index", table_name="app_tg_db")
    op.drop_column("app_tg_db", "api_hash_index")
