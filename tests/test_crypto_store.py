from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils import crypto_store


def test_no_key_keeps_plain_text(monkeypatch):
    monkeypatch.delenv("DB_ENCRYPTION_KEY", raising=False)

    plain = "hello"
    encrypted = crypto_store.encrypt_text(plain)
    assert encrypted == plain
    assert crypto_store.decrypt_text(encrypted) == plain
    assert crypto_store.blind_index("UserName") is None


def test_encrypt_decrypt_roundtrip_with_key(monkeypatch):
    monkeypatch.setenv("DB_ENCRYPTION_KEY", "test-key-123")

    plain = "hello"
    encrypted = crypto_store.encrypt_text(plain)
    assert encrypted is not None
    assert encrypted != plain
    assert encrypted.startswith("enc:v1:")
    assert crypto_store.decrypt_text(encrypted) == plain


def test_encrypt_is_idempotent(monkeypatch):
    monkeypatch.setenv("DB_ENCRYPTION_KEY", "test-key-123")

    first = crypto_store.encrypt_text("secret")
    second = crypto_store.encrypt_text(first)
    assert second == first
    assert crypto_store.decrypt_text(second) == "secret"


def test_blind_index_is_stable_and_case_insensitive(monkeypatch):
    monkeypatch.setenv("DB_ENCRYPTION_KEY", "test-key-123")

    one = crypto_store.blind_index("  @UserName ")
    two = crypto_store.blind_index("@username")
    assert one == two
    assert one is not None
