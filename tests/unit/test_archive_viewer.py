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
        with request("/api/application") as response:
            info = json.load(response)
            assert info["version"] and info["state"] == "source"
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
        with request("/api/calendar?chat=456%3A789&offset=60") as response:
            assert json.load(response)["days"] == [{"day": "1970-01-01", "start": 0, "count": 1}]
        with request("/api/messages?chat=456%3A789&start=0") as response:
            assert json.load(response)["messages"][0]["id"] == backup.message
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


def test_calendar_lists_only_saved_local_days_and_opens_their_first_message(viewer_backup):
    from datetime import datetime, timezone

    archive = Archive.open(viewer_backup.zip, viewer_backup.secret)
    try:
        original = archive.chats["456:789"][0]
        def epoch(day):
            return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())
        archive.chats["456:789"] = [original | {"message_id": index, "sent_at": when} for index, when in
            enumerate([None, epoch("2026-11-01T23:30:00"), epoch("2026-11-02T10:00:00"),
                       epoch("2026-11-06T10:00:00")], 1)]
        days = archive.calendar("456:789", 60)["days"]
        assert days == [{"day": "2026-11-02", "start": 1, "count": 2},
                        {"day": "2026-11-06", "start": 3, "count": 1}]
        assert archive.page("456:789", start=days[0]["start"])["messages"][0]["message_id"] == 2
        assert archive.calendar("456:789", -60)["days"][0]["day"] == "2026-11-01"
        with pytest.raises(ValueError):
            archive.calendar("456:789", 2000)
    finally:
        archive.close()


def test_date_jump_pages_in_both_directions_without_losing_messages(viewer_backup):
    archive = Archive.open(viewer_backup.zip, viewer_backup.secret)
    try:
        original = archive.chats["456:789"][0]
        archive.chats["456:789"] = [original | {"message_id": index} for index in range(125)]
        middle = archive.page("456:789", start=20)
        assert middle["before"] == 20 and middle["after"] == 70
        older = archive.page("456:789", before=middle["before"])
        newer = archive.page("456:789", start=middle["after"])
        last = archive.page("456:789", start=newer["after"])
        saved = [row["message_id"] for page in [older, middle, newer, last] for row in page["messages"]]
        assert saved == list(range(125))
        assert older["before"] is None and last["after"] is None
    finally:
        archive.close()


def test_workspace_queries_export_and_pagination_do_not_duplicate_partial_page(viewer_backup):
    from archive_viewer import inspection
    archive = Archive.open(viewer_backup.zip, viewer_backup.secret)
    try:
        original = archive.chats["456:789"][0]
        archive.chats["456:789"] = [original | {"message_id": index} for index in range(1, 62)]
        saved = list(inspection.messages(archive, "456:789"))
        assert len(saved) == len({row["message_id"] for row in saved}) == 61
        latest = inspection.search(archive, "456:789", query="private-message")
        earlier = inspection.search(archive, "456:789", query="private-message", before=latest["before"])
        assert latest["total"] == 61 and len(latest["messages"]) + len(earlier["messages"]) == 61
        assert not inspection.search(archive, "456:789", query="absent")["messages"]
        assert not inspection.search(archive, "456:789", start="2030-01-01")["messages"]
        info = inspection.inspect_chat(archive, "456:789")
        assert info["messages"] == 61 and info["original_missing"] == 61
        assert len(inspection.gallery(archive, "456:789")["items"]) == 60
        export = inspection.export_chat(archive, "456:789", html=True)
        assert b"<script>private-message</script>" not in export
        assert b"&lt;script&gt;private-message&lt;/script&gt;" in export
    finally:
        archive.close()
