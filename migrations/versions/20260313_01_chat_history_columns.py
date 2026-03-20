"""Add chat history columns and indexes

Revision ID: 20260313_01
Revises: 20260308_01
Create Date: 2026-03-13 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260313_01"
down_revision = "20260308_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("history_users_db", sa.Column("chat_id", sa.BigInteger(), nullable=True))
    op.add_column("history_users_db", sa.Column("account_user_id", sa.BigInteger(), nullable=True))
    op.create_index(op.f("ix_history_users_db_chat_id"), "history_users_db", ["chat_id"], unique=False)
    op.create_index(op.f("ix_history_users_db_account_user_id"), "history_users_db", ["account_user_id"], unique=False)
    op.create_index(op.f("ix_history_users_db_date"), "history_users_db", ["date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_history_users_db_date"), table_name="history_users_db")
    op.drop_index(op.f("ix_history_users_db_account_user_id"), table_name="history_users_db")
    op.drop_index(op.f("ix_history_users_db_chat_id"), table_name="history_users_db")
    op.drop_column("history_users_db", "account_user_id")
    op.drop_column("history_users_db", "chat_id")
