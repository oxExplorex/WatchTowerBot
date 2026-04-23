"""cleanup legacy username history unique

Revision ID: 265b5079295f
Revises: 20260321_03
Create Date: 2026-04-23 20:45:58.927011
"""
from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = '265b5079295f'
down_revision = '20260321_03'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        """
        ALTER TABLE username_history_db
        DROP CONSTRAINT IF EXISTS username_history_db_user_id_key
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'uq_username_history_db_user_username_hash'
            ) THEN
                ALTER TABLE username_history_db
                ADD CONSTRAINT uq_username_history_db_user_username_hash
                UNIQUE (user_id, username_hash);
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_username_history_db_username_hash
        ON username_history_db (username_hash)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        """
        ALTER TABLE username_history_db
        DROP CONSTRAINT IF EXISTS uq_username_history_db_user_username_hash
        """
    )
    op.execute(
        """
        ALTER TABLE username_history_db
        ADD CONSTRAINT username_history_db_user_id_key UNIQUE (user_id)
        """
    )
