"""Add encryption support columns for account and user identifiers.

Revision ID: 20260321_03
Revises: 20260321_02
Create Date: 2026-03-21 01:20:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260321_03"
down_revision = "20260321_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("apps_db") as batch_op:
        batch_op.add_column(sa.Column("number_hash", sa.String(), nullable=True))
        batch_op.create_index("ix_apps_db_number_hash", ["number_hash"], unique=False)

    with op.batch_alter_table("user_db") as batch_op:
        batch_op.add_column(sa.Column("username_hash", sa.String(), nullable=True))
        batch_op.create_index("ix_user_db_username_hash", ["username_hash"], unique=False)

    with op.batch_alter_table("username_history_db") as batch_op:
        batch_op.add_column(sa.Column("username_hash", sa.String(), nullable=True))
        batch_op.create_index("ix_username_history_db_username_hash", ["username_hash"], unique=False)
        batch_op.drop_constraint("uq_username_history_db_user_username", type_="unique")
        batch_op.drop_index("ix_username_history_db_username")
        batch_op.create_unique_constraint(
            "uq_username_history_db_user_username_hash",
            ["user_id", "username_hash"],
        )


def downgrade() -> None:
    with op.batch_alter_table("username_history_db") as batch_op:
        batch_op.drop_constraint("uq_username_history_db_user_username_hash", type_="unique")
        batch_op.create_index("ix_username_history_db_username", ["username"], unique=False)
        batch_op.create_unique_constraint("uq_username_history_db_user_username", ["user_id", "username"])
        batch_op.drop_index("ix_username_history_db_username_hash")
        batch_op.drop_column("username_hash")

    with op.batch_alter_table("user_db") as batch_op:
        batch_op.drop_index("ix_user_db_username_hash")
        batch_op.drop_column("username_hash")

    with op.batch_alter_table("apps_db") as batch_op:
        batch_op.drop_index("ix_apps_db_number_hash")
        batch_op.drop_column("number_hash")
