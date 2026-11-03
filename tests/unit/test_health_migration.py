import io
import types
from unittest.mock import Mock

from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_health_migration_emits_only_matching_postgresql_constraint_drop(monkeypatch, offline_module):
    module = offline_module("migrations/versions/20261103_01_preserve_account_health.py")
    inspector = types.SimpleNamespace(get_foreign_keys=Mock(return_value=[
        {"name": "account_health_db_account_uuid_fkey", "constrained_columns": ["account_uuid"], "referred_table": "apps_db"},
        {"name": "unrelated_fkey", "constrained_columns": ["admin_id"], "referred_table": "user_db"},
    ]))
    monkeypatch.setattr(module.sa, "inspect", Mock(return_value=inspector))
    output = io.StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        module.upgrade()
    sql = output.getvalue()
    assert "DROP CONSTRAINT account_health_db_account_uuid_fkey" in sql
    assert "unrelated_fkey" not in sql
    assert "DELETE" not in sql
