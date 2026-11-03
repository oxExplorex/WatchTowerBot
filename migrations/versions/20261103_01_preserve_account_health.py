"""Keep health history independently of deleted accounts.

Revision ID: 20261103_01
Revises: 265b5079295f
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20261103_01"
down_revision = "265b5079295f"
branch_labels = None
depends_on = None

_FK_NAME = "fk_account_health_db_account_uuid_apps_db"
_NAMING = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}


def upgrade() -> None:
    foreign_keys = sa.inspect(op.get_bind()).get_foreign_keys("account_health_db")
    matching = [
        fk for fk in foreign_keys
        if fk["constrained_columns"] == ["account_uuid"] and fk["referred_table"] == "apps_db"
    ]
    if matching:
        with op.batch_alter_table("account_health_db", naming_convention=_NAMING) as batch:
            for foreign_key in matching:
                batch.drop_constraint(foreign_key["name"] or _FK_NAME, type_="foreignkey")


def downgrade() -> None:
    # Never delete historical events just to make an old constraint fit again.
    orphan = op.get_bind().execute(sa.text(
        "SELECT 1 FROM account_health_db h LEFT JOIN apps_db a ON a.uuid=h.account_uuid "
        "WHERE a.uuid IS NULL LIMIT 1"
    )).first()
    if orphan:
        raise RuntimeError("Cannot restore account health foreign key while retained history exists")
    with op.batch_alter_table("account_health_db", naming_convention=_NAMING) as batch:
        batch.create_foreign_key(_FK_NAME, "apps_db", ["account_uuid"], ["uuid"])
