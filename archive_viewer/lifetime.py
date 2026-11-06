"""Track browser connections, allowing page reloads before closing the process."""
import threading
import time


class BrowserLifetime:
    def __init__(self, *, grace=15, startup_timeout=180, clock=time.monotonic):
        self.clock, self.grace = clock, grace
        self.startup_deadline = clock() + startup_timeout
        self.lock = threading.Lock()
        self.connections = 0
        self.closed_at = None

    def connected(self):
        with self.lock:
            self.connections += 1
            self.closed_at = None

    def disconnected(self):
        with self.lock:
            self.connections = max(0, self.connections - 1)
            if not self.connections:
                self.closed_at = self.clock()

    def expired(self):
        with self.lock:
            if self.connections:
                return False
            deadline = self.startup_deadline if self.closed_at is None else self.closed_at + self.grace
            return self.clock() >= deadline
