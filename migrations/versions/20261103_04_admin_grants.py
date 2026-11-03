"""Keep explicit administrator grants independent of contact profiles."""
import time

from alembic import op
import sqlalchemy as sa

revision = "20261103_04"
down_revision = "20261103_03"
branch_labels = None
depends_on = None


def upgrade():
    grants = op.create_table("admin_grant",
        sa.Column("user_id", sa.BigInteger(), primary_key=True),
        sa.Column("granted_by", sa.BigInteger()),
        sa.Column("created_at", sa.BigInteger(), nullable=False))
    users = sa.table("user_db", sa.column("user_id", sa.BigInteger()), sa.column("roles", sa.String()))
    # Runtime passes public configured IDs; no .env or application imports here.
    config = op.get_context().config
    configured = config.attributes.get("configured_admin_ids", []) if config is not None else []
    legacy = sa.select(users.c.user_id, sa.null(), sa.literal(int(time.time()))).where(
        users.c.roles == "admin", users.c.user_id > 0)
    if configured:
        legacy = legacy.where(users.c.user_id.not_in(configured))
    op.execute(grants.insert().from_select(["user_id", "granted_by", "created_at"], legacy))


def downgrade():
    op.drop_table("admin_grant")
