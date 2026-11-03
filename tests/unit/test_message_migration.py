import io

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest


@pytest.mark.parametrize("script,expected", [
    ("20261103_02_message_history.py", ["CREATE TABLE stored_message", "CREATE TABLE message_revision", "CREATE TABLE pending_message_deletion"]),
    ("20261103_03_media_archive.py", ["CREATE TABLE message_attachment"]),
    ("20261103_04_admin_grants.py", ["CREATE TABLE admin_grant"]),
    ("20261104_01_service_secrets.py", ["ALTER TABLE app_tg_db ADD COLUMN api_hash_index", "CREATE UNIQUE INDEX uq_app_tg_db_user_app_hash_index"]),
    ("20261104_02_personal_archive_keys.py", ["CREATE TABLE owner_archive_key", "ALTER TABLE message_attachment ADD COLUMN encryption_version"]),
])
def test_migrations_compile_for_postgresql(offline_module, script, expected):
    module = offline_module("migrations/versions/" + script)
    output = io.StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        module.upgrade()
    for fragment in expected:
        assert fragment in output.getvalue()
