"""Exercise real HTTP downloads and a child updater in disposable installations."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import zipfile


def test_two_isolated_installations_update_from_release_and_reject_bad_hash():
    root = Path(__file__).resolve().parents[2]
    output = root / "dist" / "update-smoke"
    output.mkdir(parents=True, exist_ok=True)
    source_files = {name: (root / name).read_bytes() for name in
                    ("scripts/update_bot.py", "core/bot_release.py")}
    main = b"from pathlib import Path\nprint('synthetic installation ' + Path('VERSION').read_text().strip())\n"
    packed = io.BytesIO()
    with zipfile.ZipFile(packed, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in (source_files | {"VERSION": b"2.1.4", "main.py": main,
                "loader.py": b"# synthetic loader", "requirements.txt": b"# no installation",
                "alembic.ini": b"# no migrations", "scripts/install_dependencies.py": b"# not executed"}).items():
            archive.writestr("WatchTower-Bot-2.1.4/" + name, content)
    content = packed.getvalue()
    filename = "WatchTower-Bot-2.1.4.zip"
    checksum = f"{hashlib.sha256(content).hexdigest()}  {filename}\n".encode()
    metadata = json.dumps(dict(tag_name="v2.1.4", draft=False, prerelease=False, assets=[
        dict(name=filename, size=len(content), state="uploaded"),
        dict(name=filename + ".sha256", size=len(checksum), state="uploaded")])).encode()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            if self.path.endswith("/latest"):
                data = metadata
            elif self.path.endswith(".sha256"):
                data = b"0" * 64 + checksum[64:] if self.path.startswith("/bad/") else checksum
            elif self.path.endswith(".zip"):
                data = content
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with TemporaryDirectory(prefix="release-", dir=output) as directory:
            for label, success in (("good", True), ("bad", False)):
                target = Path(directory) / label
                target.mkdir()
                for name, data in source_files.items():
                    path = target / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                (target / "VERSION").write_text("2.1.3", encoding="utf-8")
                (target / "main.py").write_bytes(main)
                (target / ".env.production").write_text("synthetic-local-config", encoding="utf-8")
                base = f"http://127.0.0.1:{server.server_port}/{label}"
                # Only the test subprocess rewires URLs to loopback. Production
                # builds accept canonical GitHub URLs and expose no HTTP override.
                runner = (
                    "import sys; sys.path.insert(0, sys.argv[1]); "
                    "from scripts import update_bot as u; from core.bot_release import BotRelease; "
                    "base=sys.argv[2]; u.release_api_url=lambda *args: base+'/latest'; "
                    "BotRelease.asset_url=lambda self, *args, checksum=False: "
                    "base+'/'+self.archive+('.sha256' if checksum else ''); "
                    "raise SystemExit(0 if u.download_and_extract_github_repo() else 1)"
                )
                result = subprocess.run([sys.executable, "-I", "-X", "utf8", "-c", runner, str(target), base],
                    cwd=target, capture_output=True, text=True, encoding="utf-8", timeout=30)
                assert result.returncode == (0 if success else 1), result.stdout + result.stderr
                expected = "2.1.4" if success else "2.1.3"
                assert (target / "VERSION").read_text() == expected
                assert (target / ".env.production").read_text() == "synthetic-local-config"
                probe = subprocess.run([sys.executable, "-I", "main.py"], cwd=target,
                    capture_output=True, text=True, encoding="utf-8", timeout=10)
                assert probe.returncode == 0 and probe.stdout.strip() == f"synthetic installation {expected}"
                assert not list(target.glob(".watchtower-update-*"))
        assert len(requests) == 6
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
