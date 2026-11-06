import base64

import pytest
from cryptography.exceptions import InvalidTag

from core.personal_crypto import (InvalidSecret, context, create_key_bundle, live_fingerprint,
                                  normalize_secret, open_text, seal_text, unlock_private_key)


@pytest.fixture(scope="module")
def archive_bundle():
    return create_key_bundle(123, "Рыжий кот 527")


def test_envelope_needs_secret_not_env_and_binds_owner_and_record(archive_bundle, monkeypatch):
    monkeypatch.setenv("DB_ENCRYPTION_KEY", "known-to-attacker")
    aad = context(123, "revision:offline")
    first = seal_text(archive_bundle["public_key"], "Личная переписка", aad)
    second = seal_text(archive_bundle["public_key"], "Личная переписка", aad)
    assert first != second
    assert "Личная" not in first
    assert "рыжийкот527" not in str(archive_bundle)
    with pytest.raises(InvalidSecret):
        unlock_private_key(123, archive_bundle, "Другой секрет")
    with pytest.raises(InvalidSecret):
        unlock_private_key(124, archive_bundle, "Рыжий кот 527")
    private = unlock_private_key(123, archive_bundle, "рыжийКОТ527")
    assert open_text(private, first, aad) == "Личная переписка"
    with pytest.raises(ValueError):
        open_text(private, first, context(124, "revision:offline"))
    raw = bytearray(base64.b64decode(first[7:]))
    raw[-1] ^= 1
    with pytest.raises(InvalidTag):
        open_text(private, "enc:v2:" + base64.b64encode(raw).decode(), aad)


@pytest.mark.parametrize("value", ["123456", "qwerty", "аааааа", "abcabc", "Пароль123", "abcdef", "abc\t123", "abc😀123", "short"])
def test_weak_or_invalid_secrets_rejected(value):
    with pytest.raises(InvalidSecret):
        normalize_secret(value)


def test_normalization_and_live_comparisons(monkeypatch):
    assert normalize_secret("Рыжий КОТ 527") == "рыжийкот527"
    first = live_fingerprint("Private")
    monkeypatch.setenv("DB_ENCRYPTION_KEY", "copied-key")
    assert live_fingerprint("Private") == first
    assert live_fingerprint("private") != first


def test_compressed_text_is_lossless_and_binds_its_compression_mode(archive_bundle):
    from core.personal_crypto import COMPRESSED_PREFIX, PREFIX

    aad = context(123, "revision:compressed")
    original = "Переписка без потери качества\n" * 1000
    sealed = seal_text(archive_bundle["public_key"], original, aad)
    assert sealed.startswith(COMPRESSED_PREFIX)
    assert len(sealed) < len(original.encode()) // 4
    private = unlock_private_key(123, archive_bundle, "Рыжий кот 527")
    assert open_text(private, sealed, aad) == original
    with pytest.raises(ValueError):
        open_text(private, PREFIX + sealed[len(COMPRESSED_PREFIX):], aad)


def test_authenticated_compressed_text_has_a_decompression_limit(archive_bundle):
    import os
    import zlib
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from core.personal_crypto import COMPRESSED_PREFIX, MAX_TEXT_BYTES, wrap_key

    aad = context(123, "revision:oversize")
    key, nonce = os.urandom(32), os.urandom(12)
    bound = aad + b"\0zlib"
    packed = zlib.compress(b"A" * (MAX_TEXT_BYTES + 1))
    raw = wrap_key(archive_bundle["public_key"], key, bound) + nonce + AESGCM(key).encrypt(nonce, packed, bound)
    sealed = COMPRESSED_PREFIX + base64.b64encode(raw).decode()
    private = unlock_private_key(123, archive_bundle, "Рыжий кот 527")
    with pytest.raises(ValueError):
        open_text(private, sealed, aad)
