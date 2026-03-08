"""Initial schema

Revision ID: 20260308_01
Revises:
Create Date: 2026-03-08 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260308_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_tg_db",
        sa.Column("uuid", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("app_id", sa.BigInteger(), nullable=True),
        sa.Column("api_hash", sa.String(), nullable=True),
        sa.Column("tag_name", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("uuid"),
        sa.UniqueConstraint("user_id", "app_id", "api_hash", name="uq_app_tg_db_user_app_hash"),
    )
    op.create_index(op.f("ix_app_tg_db_user_id"), "app_tg_db", ["user_id"], unique=False)

    op.create_table(
        "dump_chat_user_db",
        sa.Column("uuid", sa.Uuid(), nullable=False),
        sa.Column("admin_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("uuid"),
        sa.UniqueConstraint("admin_id", "chat_id", name="uq_dump_chat_user_db_admin_chat"),
    )
    op.create_index(op.f("ix_dump_chat_user_db_admin_id"), "dump_chat_user_db", ["admin_id"], unique=False)
    op.create_index(op.f("ix_dump_chat_user_db_chat_id"), "dump_chat_user_db", ["chat_id"], unique=False)

    op.create_table(
        "history_users_db",
        sa.Column("uuid", sa.Uuid(), nullable=False),
        sa.Column("admin_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("action_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("uuid"),
    )

    op.create_table(
        "user_db",
        sa.Column("uuid", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("full_name", sa.String(), nullable=True),
        sa.Column("roles", sa.String(), nullable=True),
        sa.Column("timezone_offset", sa.Integer(), nullable=False),
        sa.Column("auto_update_enabled", sa.Integer(), nullable=False),
        sa.Column("gemini_proxy", sa.String(), nullable=True),
        sa.Column("gemini_proxy_enabled", sa.Integer(), nullable=False),
        sa.Column("gemini_proxy_status", sa.Integer(), nullable=False),
        sa.Column("gemini_proxy_checked_at", sa.BigInteger(), nullable=True),
        sa.Column("gemini_proxy_last_error", sa.String(), nullable=True),
        sa.Column("update_snooze_until", sa.BigInteger(), nullable=True),
        sa.Column("update_last_notified", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("uuid"),
        sa.UniqueConstraint("user_id", name="uq_user_db_user_id"),
    )
    op.create_index(op.f("ix_user_db_roles"), "user_db", ["roles"], unique=False)
    op.create_index(op.f("ix_user_db_user_id"), "user_db", ["user_id"], unique=False)

    op.create_table(
        "username_history_db",
        sa.Column("uuid", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("date", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("uuid"),
    )
    op.create_index(op.f("ix_username_history_db_user_id"), "username_history_db", ["user_id"], unique=False)

    op.create_table(
        "version_state_db",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("local_version", sa.String(), nullable=True),
        sa.Column("remote_version", sa.String(), nullable=True),
        sa.Column("state", sa.String(), nullable=True),
        sa.Column("checked_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_version_state_db_checked_at"), "version_state_db", ["checked_at"], unique=False)

    op.create_table(
        "apps_db",
        sa.Column("uuid", sa.Uuid(), nullable=False),
        sa.Column("admin_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("app_tg", sa.Uuid(), nullable=True),
        sa.Column("number", sa.String(), nullable=True),
        sa.Column("alert_black_list", sa.Integer(), nullable=False),
        sa.Column("alert_black_list_id", sa.BigInteger(), nullable=False),
        sa.Column("alert_del_chat", sa.Integer(), nullable=False),
        sa.Column("alert_del_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("alert_new_chat", sa.Integer(), nullable=False),
        sa.Column("alert_new_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("alert_bot", sa.Integer(), nullable=False),
        sa.Column("alert_spoiler_media", sa.Integer(), nullable=False),
        sa.Column("last_update", sa.BigInteger(), nullable=True),
        sa.Column("last_dialogs_count", sa.BigInteger(), nullable=True),
        sa.Column("last_full_dialogs_scan", sa.BigInteger(), nullable=True),
        sa.Column("is_active", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["app_tg"], ["app_tg_db.uuid"]),
        sa.PrimaryKeyConstraint("uuid"),
        sa.UniqueConstraint("admin_id", "user_id", name="uq_apps_db_admin_user"),
    )
    op.create_index(op.f("ix_apps_db_admin_id"), "apps_db", ["admin_id"], unique=False)
    op.create_index(op.f("ix_apps_db_app_tg"), "apps_db", ["app_tg"], unique=False)
    op.create_index(op.f("ix_apps_db_is_active"), "apps_db", ["is_active"], unique=False)
    op.create_index(op.f("ix_apps_db_user_id"), "apps_db", ["user_id"], unique=False)

    op.create_table(
        "account_health_db",
        sa.Column("uuid", sa.Uuid(), nullable=False),
        sa.Column("account_uuid", sa.Uuid(), nullable=False),
        sa.Column("admin_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("date", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["account_uuid"], ["apps_db.uuid"]),
        sa.PrimaryKeyConstraint("uuid"),
    )
    op.create_index(op.f("ix_account_health_db_account_uuid"), "account_health_db", ["account_uuid"], unique=False)
    op.create_index(op.f("ix_account_health_db_admin_id"), "account_health_db", ["admin_id"], unique=False)
    op.create_index(op.f("ix_account_health_db_date"), "account_health_db", ["date"], unique=False)
    op.create_index(op.f("ix_account_health_db_status"), "account_health_db", ["status"], unique=False)
    op.create_index(op.f("ix_account_health_db_user_id"), "account_health_db", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_account_health_db_user_id"), table_name="account_health_db")
    op.drop_index(op.f("ix_account_health_db_status"), table_name="account_health_db")
    op.drop_index(op.f("ix_account_health_db_date"), table_name="account_health_db")
    op.drop_index(op.f("ix_account_health_db_admin_id"), table_name="account_health_db")
    op.drop_index(op.f("ix_account_health_db_account_uuid"), table_name="account_health_db")
    op.drop_table("account_health_db")

    op.drop_index(op.f("ix_apps_db_user_id"), table_name="apps_db")
    op.drop_index(op.f("ix_apps_db_is_active"), table_name="apps_db")
    op.drop_index(op.f("ix_apps_db_app_tg"), table_name="apps_db")
    op.drop_index(op.f("ix_apps_db_admin_id"), table_name="apps_db")
    op.drop_table("apps_db")

    op.drop_index(op.f("ix_version_state_db_checked_at"), table_name="version_state_db")
    op.drop_table("version_state_db")

    op.drop_index(op.f("ix_username_history_db_user_id"), table_name="username_history_db")
    op.drop_table("username_history_db")

    op.drop_index(op.f("ix_user_db_user_id"), table_name="user_db")
    op.drop_index(op.f("ix_user_db_roles"), table_name="user_db")
    op.drop_table("user_db")

    op.drop_table("history_users_db")

    op.drop_index(op.f("ix_dump_chat_user_db_chat_id"), table_name="dump_chat_user_db")
    op.drop_index(op.f("ix_dump_chat_user_db_admin_id"), table_name="dump_chat_user_db")
    op.drop_table("dump_chat_user_db")

    op.drop_index(op.f("ix_app_tg_db_user_id"), table_name="app_tg_db")
    op.drop_table("app_tg_db")
