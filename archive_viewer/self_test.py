"""Synthetic frozen-build smoke test; never reads a real archive or starts a bot."""
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
from urllib.request import Request, ProxyHandler, build_opener
from uuid import uuid4

from archive_viewer.archive import Archive
from archive_viewer.server import ViewerServer
from core.backup_format import BackupReader, BackupWriter
from core.backup_parts import PartsWriter
from core.personal_crypto import context, create_key_bundle, seal_text


def run():
    owner, secret = 123, "ПроверкаПросмотрщика123"
    bundle = create_key_bundle(owner, secret)
    # Exercise the KDF, RSA envelope and authenticated container in the frozen executable.
    stream = io.BytesIO()
    writer = BackupWriter(stream, owner, SimpleNamespace(**bundle))
    writer.record({"type": "test"})
    writer.finish()
    stream.seek(0)
    assert len(list(BackupReader(stream, owner, secret))) == 1
    with TemporaryDirectory(prefix="watchtower-viewer-check-") as directory:
        parts = PartsWriter(Path(directory), uuid4().hex)
        writer = BackupWriter(parts, owner, SimpleNamespace(**bundle))
        message, revision = str(uuid4()), str(uuid4())
        writer.record({"type": "info", "scope": "private"})
        writer.record({"type": "row", "table": "messages", "data": dict(uuid=message, owner_id=owner,
            account_user_id=456, chat_id=789, sender_id=789, message_id=1, sent_at=100,
            is_edited=False, is_deleted=False, latest_revision_uuid=revision)})
        writer.record({"type": "row", "table": "revisions", "data": dict(uuid=revision,
            message_uuid=message, version_at=100, revision_no=1, kind="new", encryption_version=2,
            payload=seal_text(bundle["public_key"], json.dumps({"text": "Тестовое сообщение", "media": []}),
                              context(owner, f"revision:{revision}")))})
        writer.record({"type": "summary"})
        writer.finish()
        paths = parts.finish()
        archive = Archive.open(paths[0], secret)
        try:
            assert archive.page("456:789")["messages"][0]["text"] == "Тестовое сообщение"
        finally:
            archive.close()
        with ViewerServer(paths[0]) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                opener = build_opener(ProxyHandler({}))
                for resource in ("/", "/app.js", "/style.css"):
                    with opener.open(Request(server.origin + resource), timeout=5) as response:
                        assert response.status == 200 and response.read()
            finally:
                server.shutdown()
                thread.join(timeout=5)
    print("Standalone viewer self-test passed")
