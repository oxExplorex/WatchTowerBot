"""UI-visible update checks; installation closes plaintext before restarting."""
import sys
import threading
from archive_viewer import updater


class UpdateStatus:
    def __init__(self, server):
        self.server = server
        self.current = updater.build_info()
        self.enabled = sys.platform == "win32" and bool(getattr(sys, "frozen", False))
        self.lock = threading.Lock()
        self.value = dict(version=self.current["app_version"], build=self.current["version"][:8],
                          state="unchecked" if self.enabled else "source", available=False)

    def status(self):
        with self.lock:
            return dict(self.value)

    def check(self):
        with self.lock:
            if not self.enabled or self.value["state"] in {"checking", "installing"}:
                return
            self.value.update(state="checking", error=None)
        def work():
            try:
                manifest = updater.fetch_manifest(self.current)
                available = updater.validate_manifest(manifest, self.current)
                result = dict(state="available" if available else "current", available=available,
                              latest=manifest.get("app_version") or manifest["version"][:8])
            except Exception as error:
                result = dict(state="error", error=type(error).__name__)
            with self.lock:
                self.value.update(result)
        threading.Thread(target=work, daemon=True).start()

    def install(self):
        with self.lock:
            if not self.enabled or not self.value.get("available") or self.value["state"] == "installing":
                raise ValueError("Update not available")
            self.value["state"] = "installing"
        def work():
            with self.server.lock:
                if self.server.archive:
                    self.server.archive.close()
                    self.server.archive = None
            if updater.maybe_update(self.server.path):
                self.server.shutdown()
            else:
                with self.lock:
                    self.value.update(state="error", error="Установка не завершена; текущая версия сохранена")
        threading.Thread(target=work, daemon=True).start()
