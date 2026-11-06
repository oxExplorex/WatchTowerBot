import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import threading
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler
from uuid import uuid4
import zipfile
import zlib

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import pytest

from archive_viewer.archive import Archive
from archive_viewer.server import ViewerServer
from core.backup_format import BackupWriter, BLOB_FRAME, InvalidBackup
from core.backup_parts import PartsWriter
from core.personal_crypto import context, create_key_bundle, seal_text, wrap_key


@pytest.fixture
def viewer_backup(tmp_path):
    owner, secret = 123, "СекретАрхива123"
    bundle = create_key_bundle(owner, secret)
    parts = PartsWriter(tmp_path / "parts", uuid4().hex)
    writer = BackupWriter(parts, owner, SimpleNamespace(**bundle))
    message_id, revision_ids, attachment_id = str(uuid4()), [str(uuid4()), str(uuid4())], str(uuid4())
    writer.record({"type": "info", "scope": "private"})
    writer.record({"type": "row", "table": "messages", "data": dict(uuid=message_id, owner_id=owner,
        account_user_id=456, chat_id=789, sender_id=789, message_id=10, sent_at=100,
        is_edited=True, is_deleted=True, history_missing_at=None, latest_revision_uuid=revision_ids[-1],
        latest_version_at=101, original_seen=False)})
    for i, revision in enumerate(revision_ids):
        payload = dict(text="<script>private-message</script>" if i else "раньше", media=[dict(kind="document", file_name="secret.txt")])
        writer.record({"type": "row", "table": "revisions", "data": dict(uuid=revision, message_uuid=message_id,
            revision_no=i + 1, version_at=100 + i, observed_at=1_700_000_000_000_000,
            kind="edit" if i else "new", encryption_version=2,
            payload=seal_text(bundle["public_key"], json.dumps(payload), context(owner, f"revision:{revision}")))})
    data = b"private-file-content"
    symmetric, nonce = os.urandom(32), os.urandom(12)
    header = b"WTM2\x01" + nonce + wrap_key(bundle["public_key"], symmetric, context(owner, "media"))
    encrypted = header + AESGCM(symmetric).encrypt(nonce, zlib.compress(data), header)
    blob = hashlib.sha256(encrypted).hexdigest()
    writer.record({"type": "row", "table": "attachments", "data": dict(uuid=attachment_id, owner_id=owner,
        revision_uuid=revision_ids[-1], position=0, status="stored", blob_key=blob)})
    writer.record({"type": "name", "user_id": 789, "full_name": "Друг <&>", "username": None})
    writer.record({"type": "blob", "key": blob, "size": len(encrypted)})
    writer.write(BLOB_FRAME, encrypted)
    writer.record({"type": "blob_end", "sha256": hashlib.sha256(encrypted).hexdigest()})
    writer.record({"type": "summary"})
    writer.finish()
    paths = parts.finish()
    target = tmp_path / "dump.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_STORED) as archive:
        for path in paths:
            archive.write(path, path.name)
    return SimpleNamespace(zip=target, parts=paths, secret=secret, message=message_id, media=attachment_id, data=data)


@pytest.mark.parametrize("zip_input", [False, True])
def test_viewer_opens_archive_versions_and_media_without_env_or_database(viewer_backup, zip_input):
    backup = viewer_backup
    archive = Archive.open(backup.zip if zip_input else backup.parts[0], backup.secret)
    directory = Path(archive.temporary.name)
    try:
        chats = archive.chat_list()
        assert chats[0]["name"] == "Друг <&>"
        message = archive.page(chats[0]["key"])["messages"][0]
        assert message["edited"] and message["deleted"] and message["versions"] == 2
        assert message["text"] == "<script>private-message</script>"
        assert message["time"] == 100 and message["edited_at"] == 101
        versions = archive.versions(backup.message)
        assert versions[-1]["time"] == 101 and versions[-1]["observed_at"] == 1_700_000_000
        assert versions[-1]["sent_at"] == 100 and not versions[-1]["original_seen"]
        assert len(archive.versions(backup.message)) == 2
        assert archive.media(backup.media) == backup.data
        assert all(backup.data not in path.read_bytes() for path in directory.iterdir())
    finally:
        archive.close()
    assert not directory.exists()
    with pytest.raises(InvalidBackup):
        Archive.open(backup.zip, "НеверныйСекрет123")


def test_loopback_viewer_requires_token_rejects_other_origins_and_locks(viewer_backup):
    backup = viewer_backup
    server = ViewerServer(backup.zip)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opener = build_opener(ProxyHandler({}))
    def request(path, body=None, *, token=True, origin=None, extra_headers=None):
        headers = {"X-Viewer-Token": server.token} if token else {}
        headers.update(extra_headers or {})
        if origin:
            headers["Origin"] = origin
        data = None if body is None else json.dumps(body).encode()
        if data is not None:
            headers["Content-Type"] = "application/json"
        return opener.open(Request(server.origin + path, data=data, headers=headers), timeout=5)
    try:
        with pytest.raises(HTTPError) as failure:
            request("/api/chats", token=False)
        assert failure.value.code == 403
        with pytest.raises(HTTPError) as failure:
            request("/api/unlock", {"secret": backup.secret}, origin="https://example.invalid")
        assert failure.value.code == 403
        with request("/api/unlock", {"secret": backup.secret}) as response:
            assert json.load(response)["ok"]
            assert response.headers["Cache-Control"] == "no-store"
        with request("/api/chats") as response:
            assert len(json.load(response)) == 1
        with request(f"/api/media/{backup.media}", extra_headers={"Range": "bytes=2-5"}) as response:
            assert response.status == 206
            assert response.headers["Content-Range"] == f"bytes 2-5/{len(backup.data)}"
            assert response.read() == backup.data[2:6]
        with pytest.raises(HTTPError) as failure:
            request(f"/api/media/{backup.media}", token=False)
        assert failure.value.code == 403
        with request("/api/lock", {}) as response:
            assert json.load(response)["ok"]
        with pytest.raises(HTTPError) as failure:
            request("/api/chats")
        assert failure.value.code == 401
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_viewer_rejects_truncated_archive(viewer_backup):
    path = viewer_backup.parts[-1]
    path.write_bytes(path.read_bytes()[:-5])
    with pytest.raises(InvalidBackup):
        Archive.open(viewer_backup.parts[0], viewer_backup.secret)


def test_standalone_self_test_uses_synthetic_data_and_bundled_assets(capsys):
    from archive_viewer.self_test import run
    run()
    assert "Standalone viewer self-test passed" in capsys.readouterr().out


def test_chats_sort_by_last_saved_message_date(viewer_backup):
    archive = Archive.open(viewer_backup.zip, viewer_backup.secret)
    try:
        row = archive.chats["456:789"][0]
        archive.chats["456:12"] = [row | {"chat_id": 12, "sent_at": 300}]
        archive.chats["456:999"] = [row | {"chat_id": 999, "sent_at": 50}]
        assert [chat["key"] for chat in archive.chat_list()] == ["456:12", "456:789", "456:999"]
    finally:
        archive.close()
