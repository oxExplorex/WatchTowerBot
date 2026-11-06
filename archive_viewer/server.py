"""Private loopback UI: random token, exact Host/Origin checks, no request logging."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import re
import threading
from urllib.parse import parse_qs, urlsplit

from archive_viewer.archive import Archive

ASSETS = Path(__file__).with_name("assets")


class ViewerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, path):
        super().__init__(("127.0.0.1", 0), Handler)
        self.path, self.archive = Path(path), None
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.origin = f"http://127.0.0.1:{self.server_port}"

    def server_close(self):
        with self.lock:
            if self.archive:
                self.archive.close()
                self.archive = None
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _host(self):
        return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

    def _auth(self):
        query = parse_qs(urlsplit(self.path).query)
        supplied = self.headers.get("X-Viewer-Token") or query.get("token", [""])[0]
        return self._host() and supplied.isascii() and secrets.compare_digest(supplied, self.server.token)

    def _send(self, data, mime="application/json; charset=utf-8", code=200, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; "
                         "connect-src 'self'; img-src 'self' blob:; media-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, value, code=200):
        self._send(json.dumps(value, ensure_ascii=False).encode("utf-8"), code=code)

    def do_GET(self):
        if not self._host():
            self._json({"error": "Доступ запрещён"}, 403)
            return
        url = urlsplit(self.path)
        static = {"/": ("index.html", "text/html; charset=utf-8"),
                  "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                  "/style.css": ("style.css", "text/css; charset=utf-8")}
        if url.path in static:
            name, mime = static[url.path]
            self._send((ASSETS / name).read_bytes(), mime)
            return
        if not self._auth():
            self._json({"error": "Доступ запрещён"}, 403)
            return
        with self.server.lock:
            archive = self.server.archive
            if archive is None:
                self._json({"error": "Архив заблокирован"}, 401)
                return
            try:
                query = parse_qs(url.query)
                if url.path == "/api/chats":
                    self._json(archive.chat_list())
                elif url.path == "/api/messages":
                    before = int(query["before"][0]) if "before" in query else None
                    self._json(archive.page(query["chat"][0], before))
                elif url.path == "/api/versions":
                    self._json(archive.versions(query["id"][0]))
                elif url.path.startswith("/api/media/"):
                    data = archive.media(url.path.rsplit("/", 1)[1])
                    mime = "application/octet-stream"
                    if data.startswith(b"\x89PNG\r\n\x1a\n"):
                        mime = "image/png"
                    elif data.startswith(b"\xff\xd8\xff"):
                        mime = "image/jpeg"
                    elif data.startswith((b"GIF87a", b"GIF89a")):
                        mime = "image/gif"
                    elif len(data) > 12 and data[4:8] == b"ftyp":
                        mime = "video/mp4"
                    elif data.startswith(b"OggS"):
                        mime = "audio/ogg"
                    extra = {}
                    if mime == "application/octet-stream" or "download" in query:
                        extra["Content-Disposition"] = 'attachment; filename="attachment.bin"'
                    extra["Accept-Ranges"] = "bytes"
                    byte_range = self.headers.get("Range")
                    if byte_range:
                        match = re.fullmatch(r"bytes=(\d+)-(\d*)", byte_range)
                        if match:
                            start = int(match[1])
                            end = min(int(match[2]) if match[2] else len(data) - 1, len(data) - 1)
                            if start <= end:
                                extra["Content-Range"] = f"bytes {start}-{end}/{len(data)}"
                                self._send(data[start:end + 1], mime, 206, extra)
                                return
                        self._send(b"", mime, 416, {"Content-Range": f"bytes */{len(data)}"})
                        return
                    self._send(data, mime, extra=extra)
                else:
                    self._json({"error": "Не найдено"}, 404)
            except Exception:
                self._json({"error": "Не удалось прочитать данные. Вложение может быть повреждено."}, 400)

    def do_POST(self):
        if not self._auth() or self.headers.get("Origin", self.server.origin) != self.server.origin:
            self._json({"error": "Доступ запрещён"}, 403)
            return
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            self._json({"error": "Неверный запрос"}, 400)
            return
        with self.server.lock:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 <= length <= 4096:
                    raise ValueError()
                value = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/api/unlock":
                    if self.server.archive:
                        self.server.archive.close()
                        self.server.archive = None
                    self.server.archive = Archive.open(self.server.path, value["secret"])
                    value.clear()
                    self._json({"ok": True})
                elif self.path == "/api/lock":
                    if self.server.archive:
                        self.server.archive.close()
                        self.server.archive = None
                    self._json({"ok": True})
                else:
                    self._json({"error": "Не найдено"}, 404)
            except Exception:
                self._json({"error": "Не удалось открыть архив. Проверьте секрет и наличие всех частей."}, 400)
