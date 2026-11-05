"""Redact credential patterns after formatting messages and tracebacks."""
import logging
import re


_CREDENTIALS = re.compile(r"(https?://)[^/\s]+@", re.IGNORECASE)
_ASSIGNMENTS = re.compile(
    r"(\b(?:api[_-]?key|api_hash|token|password|phone_number|session|number)[\"']?\s*[=:]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,\"'&}\]]+)",
    re.IGNORECASE,
)
_BOT_TOKEN = re.compile(r"(?<![A-Za-z0-9_])(?:bot)?\d{6,12}:[A-Za-z0-9_-]{20,}\b")
_GOOGLE_KEY = re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b")
_API_HASH = re.compile(r"(?<![A-Za-z0-9])[a-fA-F0-9]{32}(?![A-Za-z0-9])")


def redact_log_text(value: str) -> str:
    value = _CREDENTIALS.sub(r"\1[REDACTED]@", value)
    value = _ASSIGNMENTS.sub(r"\1[REDACTED]", value)
    value = _BOT_TOKEN.sub("[REDACTED]", value)
    value = _GOOGLE_KEY.sub("[REDACTED]", value)
    # PostgreSQL duplicate-key details can contain an unlabeled Telegram api_hash.
    return _API_HASH.sub("[REDACTED]", value)


class RedactingFormatter(logging.Formatter):
    def __init__(self, delegate: logging.Formatter):
        super().__init__()
        self.delegate = delegate

    def format(self, record: logging.LogRecord) -> str:
        return redact_log_text(self.delegate.format(record))


class LibraryErrorHandler(logging.Handler):
    """Route propagated library warnings through the application's safe handlers."""

    def __init__(self, target):
        super().__init__(logging.WARNING)
        self.target = target

    def emit(self, record):
        self.target.handle(record)


def route_library_errors(target):
    root = logging.getLogger()
    if not any(isinstance(handler, LibraryErrorHandler) and handler.target is target for handler in root.handlers):
        root.addHandler(LibraryErrorHandler(target))
