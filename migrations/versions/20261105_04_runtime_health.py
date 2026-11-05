"""Store runtime observations without interpreting old scan checks as uptime."""
from alembic import op
import sqlalchemy as sa

revision = "20261105_04"
down_revision = "20261105_03"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("runtime_health",
        sa.Column("component", sa.String(), primary_key=True),
        sa.Column("owner_id", sa.BigInteger(), primary_key=True),
        sa.Column("bucket_at", sa.BigInteger(), primary_key=True),
        sa.Column("observed_at", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("expected", sa.Integer(), nullable=False),
        sa.Column("available", sa.Integer(), nullable=False))
    op.create_index("ix_runtime_health_bucket_at", "runtime_health", ["bucket_at"])


def downgrade():
    op.drop_index("ix_runtime_health_bucket_at", table_name="runtime_health")
    op.drop_table("runtime_health")
