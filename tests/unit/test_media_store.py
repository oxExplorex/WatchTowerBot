from pathlib import Path

from cryptography.exceptions import InvalidTag
import pytest

from core.media_store import MediaQuotaExceeded, MediaStore, MediaTooLarge


@pytest.mark.parametrize("compress", [False, True])
def test_streaming_media_roundtrip_has_no_plaintext_files(tmp_path, monkeypatch, compress):
    monkeypatch.setenv("DB_ENCRYPTION_KEY", "offline-secret")
    store = MediaStore(tmp_path)
    original = ("Секретный документ\n".encode() + bytes(range(256))) * 500
    with store.writer(123, compress=compress) as writer:
        for offset in range(0, len(original), 700):
            writer.write(original[offset:offset + 700])
        key, size = writer.finish()
    assert size == len(original)
    assert store.read(123, key) == original
    content = store.path(123, key).read_bytes()
    assert "Секретный".encode() not in content
    assert not list(tmp_path.glob("*.part"))
    if compress:
        assert len(content) < len(original) // 2


def test_equal_bytes_share_one_blob_but_owners_are_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_ENCRYPTION_KEY", "offline-secret")
    store = MediaStore(tmp_path)
    results = []
    for owner, compress in ((123, False), (123, True), (456, False)):
        with store.writer(owner, compress=compress) as writer:
            writer.write(b"same-content")
            results.append(writer.finish()[0])
    assert results[0] == results[1] != results[2]
    assert len(list(tmp_path.rglob("*.wtm"))) == 2
    assert store.read(123, results[0]) == b"same-content"


@pytest.mark.parametrize("failure", ["ciphertext", "header", "truncated", "key"])
def test_media_authentication_rejects_corruption_and_wrong_key(tmp_path, monkeypatch, failure):
    monkeypatch.setenv("DB_ENCRYPTION_KEY", "offline-secret")
    store = MediaStore(tmp_path)
    with store.writer(123) as writer:
        writer.write(b"do not expose unauthenticated plaintext")
        key, _ = writer.finish()
    path = store.path(123, key)
    content = bytearray(path.read_bytes())
    if failure == "key":
        monkeypatch.setenv("DB_ENCRYPTION_KEY", "other-secret")
    elif failure == "truncated":
        path.write_bytes(content[:10])
    else:
        content[20 if failure == "ciphertext" else 4] ^= 1
        path.write_bytes(content)
    with pytest.raises((InvalidTag, ValueError)):
        store.read(123, key)


def test_failed_writes_cleanup_and_limits_are_enforced(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_ENCRYPTION_KEY", "offline-secret")
    with pytest.raises(MediaTooLarge):
        with MediaStore(tmp_path, max_file_bytes=3).writer(123) as writer:
            writer.write(b"oversize")
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(MediaQuotaExceeded):
        MediaStore(tmp_path, max_total_bytes=1).writer(123)
    monkeypatch.delenv("DB_ENCRYPTION_KEY")
    with pytest.raises(RuntimeError):
        MediaStore(tmp_path).writer(123)
    assert list(tmp_path.iterdir()) == []


def test_invalid_personal_key_cleans_up_before_context_manager_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_ENCRYPTION_KEY", "offline-secret")
    with pytest.raises(ValueError):
        MediaStore(tmp_path).writer(123, public_key="invalid-base64-key")
    assert list(tmp_path.iterdir()) == []
