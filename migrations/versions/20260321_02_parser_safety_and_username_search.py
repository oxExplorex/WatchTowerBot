"""Parser safety guards and username search constraints.

Revision ID: 20260321_02
Revises: 9199bbed0345
Create Date: 2026-03-21 00:30:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260321_02"
down_revision = "c58325f43f42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM username_history_db
        WHERE uuid IN (
            SELECT uuid FROM (
                SELECT
                    uuid,
                    ROW_NUMBER() OVER (
                        PARTITION BY user_id, username
                        ORDER BY date DESC
                    ) AS rn
                FROM username_history_db
                WHERE username IS NOT NULL
            ) t
            WHERE t.rn > 1
        )
        """
    )

    with op.batch_alter_table("apps_db") as batch_op:
        batch_op.add_column(sa.Column("baseline_sync_done", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("pending_delete_signature", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("pending_delete_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("pending_delete_since", sa.BigInteger(), nullable=True))

    with op.batch_alter_table("username_history_db") as batch_op:
        batch_op.create_index("ix_username_history_db_username", ["username"], unique=False)
        batch_op.create_unique_constraint("uq_username_history_db_user_username", ["user_id", "username"])


def downgrade() -> None:
    with op.batch_alter_table("username_history_db") as batch_op:
        batch_op.drop_constraint("uq_username_history_db_user_username", type_="unique")
        batch_op.drop_index("ix_username_history_db_username")

    with op.batch_alter_table("apps_db") as batch_op:
        batch_op.drop_column("pending_delete_since")
        batch_op.drop_column("pending_delete_count")
        batch_op.drop_column("pending_delete_signature")
        batch_op.drop_column("baseline_sync_done")
