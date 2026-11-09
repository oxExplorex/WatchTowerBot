"""Startup notifications using only the standard library, before pip/aiogram."""
from __future__ import annotations

import html
import json
import logging
import os
from pathlib import Path
import re
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from callbacks.startup import CLOSE
from data.texts.startup import CLOSE_BUTTON, RUNNING_VERSION

ROOT = Path(__file__).resolve().parents[1]
_current = None


class DeliveryError(Exception):
    def __init__(self, code=0, *, retry_after=0, unchanged=False, reason=""):
        super().__init__("Startup notification delivery failed")
        self.code, self.retry_after, self.unchanged = code, retry_after, unchanged
        self.reason = reason


class TelegramTransport:
    def __init__(self, token):
        self.token = token

    def __call__(self, method, payload):
        request = Request(f"https://api.telegram.org/bot{self.token}/{method}",
                          data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                          headers={"Content-Type": "application/json"})
        try:
            try:
                response = urlopen(request, timeout=3)
            except HTTPError as error:
                response = error
            with response:
                result = json.loads(response.read(64 * 1024))
        except (OSError, URLError, ValueError) as error:
            # Never expose an exception containing the request URL or bot token.
            raise DeliveryError(reason=type(getattr(error, "reason", error)).__name__) from None
        if not result.get("ok"):
            raise DeliveryError(result.get("error_code", 0),
                retry_after=min(3600, max(0, int(result.get("parameters", {}).get("retry_after", 0)))),
                unchanged="message is not modified" in str(result.get("description", "")).lower())
        return result.get("result")


def _ids(values):
    result = set()
    for value in values:
        try:
            number = int(value)
        except (ValueError, TypeError):
            continue
        if 10 < number < 2**63:
            result.add(number)
    return sorted(result)


def bootstrap_credentials(root=ROOT, environ=None):
    """Read only the two notification settings, with system env taking priority."""
    environ = os.environ if environ is None else environ
    values = {}
    try:
        for line in (Path(root) / ".env").read_text(encoding="utf-8-sig").splitlines():
            match = re.match(r"^\s*(?:export\s+)?(TOKEN_BOT|ADMIN_ID_LIST)\s*=\s*(.*?)\s*$", line)
            if match:
                value = match[2]
                if value.startswith(("'", '"')):
                    quote = value[0]
                    end = value.find(quote, 1)
                    value = value[1:end] if end > 0 else ""
                else:
                    value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
                values[match[1]] = value
    except (OSError, UnicodeError):
        pass
    token = environ.get("TOKEN_BOT", values.get("TOKEN_BOT", "")).strip()
    admins = environ.get("ADMIN_ID_LIST", values.get("ADMIN_ID_LIST", ""))
    return token, _ids(admins.split(","))


class StartupReporter:
    def __init__(self, token="", recipients=(), *, root=ROOT, transport=None, interval=8):
        self.root = Path(root)
        self.token = token
        self.recipients = _ids(recipients)
        self.transport = transport or TelegramTransport(token)
        self.interval = interval
        self.path = self.root / "data/temp/startup-status.json"
        self.condition = threading.Condition()
        self.thread = None
        self.running = self.closing = self.retired = False
        self.started_at = time.time()
        self.ready_at = None
        self.phase, self.detail = "", "Подготовка приложения"
        self.frames = []
        self.state = "running"
        self.sessions = ""
        self.message_ids, self.sent_text, self.blocked = {}, {}, set()
        self.dismissed = set()
        self.thread_ids = {}
        self.operation = ""
        self.revision = 0
        self.resume = False
        self._load_handoff()

    def _load_handoff(self):
        try:
            if self.path.stat().st_size > 64 * 1024:
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("messages"), dict):
                return
            if data.get("bot_id") != self.token.split(":", 1)[0]:
                return
            # Routes remain useful for ordinary launches too, before DB access.
            threads = data.get("threads", {})
            if isinstance(threads, dict):
                self.thread_ids = {int(k): int(v) for k, v in threads.items()
                                   if str(k).isdigit() and str(v).isdigit() and int(v) > 0}
            if (data.get("resume") is True and data.get("bot_id") == self.token.split(":", 1)[0]
                    and 0 <= time.time() - data["updated_at"] < 1800):
                self.started_at = min(time.time(), float(data["started_at"]))
                self.message_ids = {int(k): int(v) for k, v in data["messages"].items()
                                    if str(k).isdigit() and str(v).isdigit() and int(v) > 0}
                self.frames = [value[:100] for value in data.get("frames", []) if isinstance(value, str)][-5:]
                recipients = data.get("recipients", [])
                if isinstance(recipients, list):
                    self.recipients = _ids([*self.recipients, *recipients, *self.message_ids])
                self.operation = str(data.get("operation", ""))[:100]
        except (OSError, ValueError, TypeError, KeyError):
            pass

    def _save(self):
        if self.retired:
            return
        temporary = None
        try:
            import tempfile

            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                              prefix="startup-status-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump({"bot_id": self.token.split(":", 1)[0], "started_at": self.started_at,
                           "updated_at": time.time(), "resume": self.resume, "messages": self.message_ids,
                           "frames": self.frames[-5:], "recipients": self.recipients,
                           "threads": self.thread_ids, "operation": self.operation}, stream, ensure_ascii=False)
            os.replace(temporary, self.path)
        except OSError:
            pass
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def configure(self, token, recipients, *, thread_ids=None):
        with self.condition:
            self.token = token
            if isinstance(self.transport, TelegramTransport):
                self.transport = TelegramTransport(token)
            self.recipients = _ids([*self.recipients, *recipients])
            if thread_ids:
                for chat_id, thread_id in thread_ids.items():
                    self.thread_ids[chat_id] = thread_id
            self.revision += 1
            self._save()
            self._wake()

    def _wake(self):
        if not self.running and self.token and self.recipients:
            self.running = True
            self.thread = threading.Thread(target=self._worker, name="startup-status", daemon=True)
            self.thread.start()
        self.condition.notify_all()

    def update(self, phase, detail="", *, complete_previous=True):
        with self.condition:
            if self.phase and self.phase != phase and complete_previous:
                self.frames.append(self.phase)
                self.frames = self.frames[-5:]
            self.phase, self.detail = str(phase)[:100], str(detail)[:400]
            self.revision += 1
            self.closing = False
            self._save()
            self._wake()

    def dependencies(self, completed, total, detail=""):
        self.update("Зависимости", (f"Готово {completed} из {total}" + (f" · {detail}" if detail else ""))
                    if total else detail or "Проверка окружения")

    def render(self):
        titles = {"running": "Подготовка WatchTowerBot", "ready": "WatchTowerBot запущен",
                  "warning": "WatchTowerBot запущен с замечаниями", "failed": "WatchTowerBot · требуется проверка"}
        if self.operation == "Обновление":
            titles.update(running="Обновление WatchTowerBot", ready="WatchTowerBot обновлён",
                          warning="WatchTowerBot обновлён с замечаниями")
        lines = [f"<b>{titles[self.state]}</b>"]
        try:
            version = (self.root / "VERSION").read_text(encoding="utf-8-sig").strip()[:40]
            lines.append(RUNNING_VERSION.format(version=html.escape(version)) if self.state in {"ready", "warning"}
                         else f"Версия <code>{html.escape(version)}</code>")
        except OSError:
            pass
        lines.append("")
        for phase in self.frames[-4:]:
            lines.append(f"✓ {html.escape(phase)}")
        lines.append(f"<b>{html.escape(self.phase)}</b>")
        if self.detail:
            lines.append(html.escape(self.detail))
        if self.sessions:
            lines.extend(["", html.escape(self.sessions)])
        seconds = max(0, int((self.ready_at or time.time()) - self.started_at))
        lines.extend(["", f"<i>Время: {seconds // 60} мин {seconds % 60} с</i>"])
        return "\n".join(lines)

    def finish(self, *, success=True, detail=""):
        with self.condition:
            self.ready_at = time.time()
            self.state = ("warning" if self.sessions.startswith("Требуют") else "ready") if success else "failed"
            self.resume = False
            self.update("Готово" if success else "Требуется проверка", detail, complete_previous=success)
            self.closing = True
            self.condition.notify_all()

    def fail(self, error):
        if self.state == "failed":
            return
        name = type(error).__name__[:80]
        self.finish(success=False, detail=f"Этап: {self.phase[:80] or 'запуск'}. {self.detail[:120]}. Ошибка: {name}. Проверьте локальные логи и выполните ручной запуск после исправления.")

    def session_result(self, ready, total):
        with self.condition:
            self.sessions = (f"Личные Telegram-сессии: {ready} из {total} подключены." if ready == total
                             else f"Требуют проверки Telegram-сессии: {total - ready} из {total}. Бот продолжает работу.")
            if self.state in {"ready", "warning"}:
                self.state = "ready" if ready == total else "warning"
            self.revision += 1
            self._wake()
            if self.ready_at is not None:
                self.closing = True

    def prepare_restart(self):
        with self.condition:
            self.update("Перезапуск", "Код подготовлен. Приложение запускается заново.")
            self.resume = True
            self._save()
            self.closing = True
            self.condition.notify_all()

    def close(self, timeout=8):
        with self.condition:
            self.closing = True
            self.condition.notify_all()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=timeout)

    def dismiss(self, chat_id, message_id):
        with self.condition:
            if self.message_ids.get(chat_id) == message_id:
                self.dismissed.add(chat_id)


    def _deliver(self, chat_id, text, *, alert=False):
        common = dict(chat_id=chat_id, text=text, parse_mode="HTML")
        common["reply_markup"] = ({"inline_keyboard": [[
            {"text": CLOSE_BUTTON, "callback_data": CLOSE}
        ]]} if self.state in {"ready", "warning", "failed"} else {"inline_keyboard": []})
        identity = self.message_ids.get(chat_id)
        if identity and not alert:
            try:
                self.transport("editMessageText", dict(common, message_id=identity))
                return
            except DeliveryError as error:
                if error.unchanged:
                    return
                if error.code != 400:
                    raise
        if thread_id := self.thread_ids.get(chat_id):
            common["message_thread_id"] = thread_id
        try:
            result = self.transport("sendMessage", dict(common, disable_notification=not alert))
        except DeliveryError as error:
            if error.code != 400 or "message_thread_id" not in common:
                raise
            # A deleted/closed topic must not hide a startup failure completely.
            common.pop("message_thread_id")
            result = self.transport("sendMessage", dict(common, disable_notification=not alert))
        with self.condition:
            self.message_ids[chat_id] = int(result["message_id"])
            self._save()

    def _worker(self):
        sent_revision, last_send, retry_at = -1, None, 0
        while True:
            with self.condition:
                if self.retired or (self.closing and self.revision == sent_revision):
                    self.running = False
                    return
                if self.revision == sent_revision:
                    self.condition.wait()
                    continue
                next_send = last_send + self.interval if last_send is not None and not self.closing else 0
                delay = max(retry_at, next_send) - time.monotonic()
                if delay > 0:
                    if self.closing and retry_at > time.monotonic():
                        self.running = False
                        return
                    self.condition.wait(delay)
                    continue
                revision, text, recipients = self.revision, self.render(), list(self.recipients)
                alert = self.state == "failed"
            retry = False
            for chat_id in recipients:
                if chat_id in self.blocked or chat_id in self.dismissed or self.sent_text.get(chat_id) == text:
                    continue
                try:
                    self._deliver(chat_id, text, alert=alert)
                    self.sent_text[chat_id] = text
                except DeliveryError as error:
                    logger = logging.getLogger("gemini_message_manager")
                    if logger.handlers:
                        log = logger.warning if error.code else logger.debug
                        log("Startup notification delivery deferred: chat_id=%s code=%s reason=%s retry_after=%s",
                            chat_id, error.code, error.reason or "telegram_api", error.retry_after)
                    if error.code in (401, 403):
                        self.blocked.add(chat_id)
                    else:
                        retry_at = max(retry_at, time.monotonic() + (error.retry_after or 15))
                        retry = True
                except Exception:
                    # Notification failures never break startup or reveal errors.
                    retry_at, retry = time.monotonic() + 15, True
            with self.condition:
                last_send = time.monotonic()
                if not retry or self.closing:
                    sent_revision = revision


def start_bootstrap_notifications(root=ROOT):
    global _current
    token, recipients = bootstrap_credentials(root)
    _current = StartupReporter(token, recipients, root=root)
    _current.update("Подготовка", "Бот запускается. Проверяем окружение.")
    previous_hook = sys.excepthook

    def report_import_failure(kind, error, traceback):
        if _current is not None and _current.state != "failed":
            _current.fail(error)
            _current.close()
        previous_hook(kind, error, traceback)

    sys.excepthook = report_import_failure
    return _current


def current_reporter():
    return _current


def begin_operation(label, recipients=None, message=None):
    global _current
    if _current is None:
        return None
    previous = _current
    with previous.condition:
        previous.retired = True
        previous.condition.notify_all()
    targets = list(recipients if recipients is not None else previous.recipients)
    chat_id = getattr(getattr(message, "chat", None), "id", None)
    if isinstance(chat_id, int) and chat_id > 10:
        targets.append(chat_id)
    _current = StartupReporter(previous.token, targets, root=previous.root, transport=previous.transport)
    _current.operation = label
    _current.thread_ids.update(previous.thread_ids)
    # The settings panel is not an operation log. The async sender creates a
    # separate message in Logs before starting the worker or downloading code.
    _current.message_ids.clear()
    _current.frames.clear()
    _current.phase, _current.detail = label, "Подготовка приложения к перезапуску."
    _current._save()
    return _current
