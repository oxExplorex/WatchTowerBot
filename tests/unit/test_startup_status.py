import io
import json
from pathlib import Path
import threading
import time
from urllib.error import URLError

import pytest

from scripts import startup_status as status


class Transport:
    def __init__(self):
        self.calls = []
        self.first = threading.Event()

    def __call__(self, method, payload):
        self.calls.append((method, payload))
        self.first.set()
        return {"message_id": 700}


def reporter(tmp_path, transport=None, interval=0):
    (tmp_path / "VERSION").write_text("2.0.0", encoding="utf-8")
    return status.StartupReporter("123456:synthetic_test_token", [123], root=tmp_path,
                                  transport=transport or Transport(), interval=interval)


def test_html_and_bursts_are_coalesced_with_a_permanent_final_message(tmp_path):
    sender = Transport()
    report = reporter(tmp_path, sender, interval=60)
    report.update("Подготовка", "Бот запускается")
    assert sender.first.wait(3)
    for count in range(1, 17):
        report.dependencies(count, 16, "пакет <unsafe>")
    assert "&lt;unsafe&gt;" in report.render()
    report.finish(detail="Обработчики готовы")
    report.close(timeout=3)
    assert not report.running
    assert [method for method, _ in sender.calls] == ["sendMessage", "editMessageText"]
    assert sender.calls[-1][1]["message_id"] == 700
    assert "<b>WatchTowerBot запущен</b>" in sender.calls[-1][1]["text"]
    assert "✓ Зависимости" in report.render()
    assert report.render().count("<b>") == 2


def test_fatal_failure_sends_a_new_alert_instead_of_silently_editing_progress(tmp_path):
    sender = Transport()
    report = reporter(tmp_path, sender)
    report.update("Подготовка", "Запуск")
    assert sender.first.wait(3)
    report.fail(RuntimeError("password=private-never-send"))
    report.close(timeout=3)
    method, payload = sender.calls[-1]
    assert method == "sendMessage" and payload["disable_notification"] is False
    assert "RuntimeError" in payload["text"] and "private-never-send" not in payload["text"]
    assert sum(not values.get("disable_notification", True) for _, values in sender.calls) == 1


def test_edit_failure_sends_replacement_and_handoff_reuses_new_message_id(tmp_path):
    sender = Transport()

    def delivery(method, payload):
        if method == "editMessageText" and payload["message_id"] == 500:
            sender.calls.append((method, payload))
            raise status.DeliveryError(400)
        return sender(method, payload)

    report = reporter(tmp_path, delivery)
    report.message_ids[123] = 500
    report.update("Обновление", "Подготовка")
    report.prepare_restart()
    report.close(timeout=3)
    assert [method for method, _ in sender.calls][:2] == ["editMessageText", "sendMessage"]
    assert report.message_ids[123] == 700
    content = report.path.read_text(encoding="utf-8")
    assert "synthetic_test_token" not in content
    after = reporter(tmp_path, sender)
    assert after.message_ids[123] == 700
    after.finish(detail="Перезапуск завершён")
    after.close(timeout=3)
    assert sender.calls[-1][0] == "editMessageText"
    assert sender.calls[-1][1]["message_id"] == 700


@pytest.mark.parametrize("code", [403, 429, 0])
def test_delivery_errors_do_not_flood_or_break_startup(tmp_path, code):
    calls = []
    first = threading.Event()

    def fail(method, payload):
        calls.append(method)
        first.set()
        raise status.DeliveryError(code, retry_after=60 if code == 429 else 0)

    report = reporter(tmp_path, fail)
    report.update("Зависимости", "Готово 6 из 16")
    assert first.wait(3)
    report.fail(RuntimeError("password=must-not-appear, token=private"))
    report.close(timeout=3)
    assert not report.running
    assert len(calls) == 1
    assert "password=" not in report.render() and "token=" not in report.render()
    assert "RuntimeError" in report.render()
    assert "Готово 6 из 16" in report.render()
    assert "✓ Зависимости" not in report.render()


def test_env_reader_uses_only_notification_fields_with_system_priority(tmp_path):
    (tmp_path / ".env").write_text("export TOKEN_BOT='file-token'\nADMIN_ID_LIST=123, 456, bad, -1\nDB_PASSWORD=do-not-load\n", encoding="utf-8")
    assert status.bootstrap_credentials(tmp_path, {}) == ("file-token", [123, 456])
    assert status.bootstrap_credentials(tmp_path, {"TOKEN_BOT": "system-token", "ADMIN_ID_LIST": "789"}) == ("system-token", [789])


@pytest.mark.parametrize("content", ["[]", "broken", '{"messages": []}', '{"messages": {}, "resume": true}'])
def test_broken_handoff_never_blocks_startup(tmp_path, content):
    path = tmp_path / "data/temp/startup-status.json"
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")
    report = reporter(tmp_path)
    report.finish()
    report.close(timeout=3)
    assert report.state == "ready"


def test_transport_uses_html_utf8_and_hides_token_in_network_errors(monkeypatch):
    received = []

    def open_request(request, timeout):
        received.append(json.loads(request.data))
        return io.BytesIO(b'{"ok": true, "result": {"message_id": 1}}')

    monkeypatch.setattr(status, "urlopen", open_request)
    send = status.TelegramTransport("synthetic-private-token")
    assert send("sendMessage", {"chat_id": 123, "text": "<b>Запуск</b>", "parse_mode": "HTML"}) == {"message_id": 1}
    assert received[0]["text"] == "<b>Запуск</b>"

    def offline(*args, **kwargs):
        raise URLError("https://api.telegram.org/botsynthetic-private-token/sendMessage")

    monkeypatch.setattr(status, "urlopen", offline)
    with pytest.raises(status.DeliveryError) as error:
        send("sendMessage", {})
    assert "synthetic-private-token" not in str(error.value)
