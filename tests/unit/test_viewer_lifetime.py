import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from archive_viewer.lifetime import BrowserLifetime
from archive_viewer.server import ViewerServer


def test_last_tab_grace_allows_reload_and_keeps_other_tabs_alive():
    now = [0]
    lifetime = BrowserLifetime(grace=15, startup_timeout=180, clock=lambda: now[0])
    lifetime.connected()
    lifetime.connected()
    lifetime.disconnected()
    now[0] = 1000
    assert not lifetime.expired()  # An open background tab needs no JS timer.
    lifetime.disconnected()
    now[0] += 14
    assert not lifetime.expired()
    lifetime.connected()  # Reload replaces the connection during the grace period.
    now[0] += 1000
    assert not lifetime.expired()
    lifetime.disconnected()
    now[0] += 15
    assert lifetime.expired()


def test_browser_that_never_connects_does_not_leave_an_abandoned_process():
    now = [0]
    lifetime = BrowserLifetime(startup_timeout=180, clock=lambda: now[0])
    now[0] = 179
    assert not lifetime.expired()
    now[0] = 180
    assert lifetime.expired()


def wait_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        threading.Event().wait(.01)
    assert predicate()


def test_closing_last_real_stream_stops_server_and_clears_archive(monkeypatch):
    import archive_viewer.server as module

    monkeypatch.setattr(module, "SESSION_PING_INTERVAL", .03)
    server = ViewerServer("synthetic-unused-path", watch_browser=True)
    server.browser_lifetime = BrowserLifetime(grace=.1, startup_timeout=5)
    close = Mock()
    server.archive = SimpleNamespace(close=close)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    thread.start()
    opener = build_opener(ProxyHandler({}))
    streams = []
    try:
        with pytest.raises(HTTPError) as error:
            opener.open(server.origin + "/api/session", timeout=2)
        assert error.value.code == 403 and server.browser_lifetime.connections == 0
        for _ in range(2):
            stream = opener.open(Request(server.origin + "/api/session?token=" + server.token), timeout=2)
            streams.append(stream)
            assert stream.readline() == b": connected\n"
        assert server.browser_lifetime.connections == 2
        streams[0].close()
        wait_until(lambda: server.browser_lifetime.connections == 1)
        assert thread.is_alive()
        streams[1].close()
        thread.join(timeout=3)
        assert not thread.is_alive()
        close.assert_called_once()
        assert server.archive is None
    finally:
        for stream in streams:
            stream.close()
        if thread.is_alive():
            server.shutdown()
            thread.join(timeout=3)
        server.server_close()


def test_explicit_exit_requires_token_and_same_origin_and_stops_even_without_watchdog():
    server = ViewerServer("synthetic-unused-path")
    close = Mock()
    server.archive = SimpleNamespace(close=close)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    thread.start()
    opener = build_opener(ProxyHandler({}))
    headers = {"X-Viewer-Token": server.token, "Content-Type": "application/json"}
    try:
        for denied in ({"Content-Type": "application/json"}, headers | {"Origin": "https://example.invalid"}):
            with pytest.raises(HTTPError) as error:
                opener.open(Request(server.origin + "/api/exit", data=b"{}", headers=denied), timeout=2)
            assert error.value.code == 403
        close.assert_not_called()
        with opener.open(Request(server.origin + "/api/exit", data=b"{}", headers=headers), timeout=2) as response:
            assert json.load(response) == {"ok": True}
        thread.join(timeout=3)
        assert not thread.is_alive() and server.archive is None
        close.assert_called_once()
    finally:
        if thread.is_alive():
            server.shutdown()
            thread.join(timeout=3)
        server.server_close()
