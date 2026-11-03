import io
import logging
import sys
import types
from unittest.mock import AsyncMock

import pytest

from core.log_safety import RedactingFormatter, redact_log_text


@pytest.mark.parametrize("message,private", [
    ("api_hash=synthetic-private-hash", "synthetic-private-hash"),
    ('{"api_hash": "synthetic-private-hash"}', "synthetic-private-hash"),
    ("https://user:private-password@127.0.0.1:8080", "private-password"),
    ("session=79000000001", "79000000001"),
    ("Key (api_hash)=(" + "a" * 32 + ")", "a" * 32),
    ("key=AIza" + "A" * 35, "AIza" + "A" * 35),
    ("https://api.telegram.org/bot123456:" + "A" * 30 + "/getMe", "123456:" + "A" * 30),
])
def test_known_credential_patterns_are_redacted(message, private):
    assert private not in redact_log_text(message)


def test_quoted_credentials_with_spaces_and_at_signs_are_fully_redacted():
    assert redact_log_text('password="private words"') == "password=[REDACTED]"
    assert redact_log_text("http://user:private@password@host:8080") == "http://[REDACTED]@host:8080"


def test_formatter_redacts_exception_text_and_preserves_stack_location():
    stream = io.StringIO()
    logger = logging.Logger("offline-redaction")
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingFormatter(logging.Formatter("%(message)s")))
    logger.addHandler(handler)
    try:
        raise RuntimeError("http://user:synthetic-private-password@127.0.0.1:8080")
    except RuntimeError:
        logger.exception("Request failed")
    output = stream.getvalue()
    assert "synthetic-private-password" not in output
    assert "Traceback" in output
    assert "test_log_safety.py" in output


@pytest.mark.asyncio
async def test_error_handler_does_not_log_update_or_exception_payload(monkeypatch, offline_module, caplog):
    loader = types.ModuleType("loader")
    loader.router = types.SimpleNamespace(error=lambda: lambda function: function)
    monkeypatch.setitem(sys.modules, "loader", loader)
    module = offline_module("handlers/errors/error_handler.py")
    event = types.SimpleNamespace(
        exception=RuntimeError("synthetic-private-exception"),
        update=types.SimpleNamespace(update_id=123, message="synthetic-private-message"),
    )
    with caplog.at_level(logging.ERROR):
        await module.errors_handler(event)
    assert "synthetic-private" not in caplog.text
    assert "RuntimeError" in caplog.text
    assert "update_id=123" in caplog.text
