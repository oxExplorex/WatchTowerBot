from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_connect_database_requires_encryption_key(database_module, monkeypatch, tmp_path):
    monkeypatch.setenv("DB_ENCRYPTION_KEY", "")
    with pytest.raises(RuntimeError, match="DB_ENCRYPTION_KEY is required"):
        await database_module.connect_database()
    assert not database_module.is_connected()
    assert not (tmp_path / "test_db.sqlite3").exists()
