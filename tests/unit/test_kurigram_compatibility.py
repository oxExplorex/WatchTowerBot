from importlib import metadata

import pytest

from pyrogram import Client, compose, filters
from pyrogram.errors import FloodWait, InternalServerError, PhoneCodeExpired, RPCError, SessionPasswordNeeded
from pyrogram.handlers import MessageHandler
from pyrogram.types import Chat, Message, User

from scripts.install_dependencies import KURIGRAM_VERSION


def test_installed_distribution_matches_reviewed_release():
    assert metadata.version("Kurigram") == KURIGRAM_VERSION


def test_required_client_api_is_available_without_connecting():
    for method in (
        "connect", "disconnect", "start", "stop", "send_phone_number_code",
        "sign_in", "check_password", "get_dialogs", "get_dialogs_count",
        "get_me", "download_media", "add_handler",
    ):
        assert callable(getattr(Client, method))
    assert callable(compose)
    assert callable(MessageHandler)
    assert filters.text is not None
    assert all(issubclass(error, RPCError) for error in (
        FloodWait, InternalServerError, PhoneCodeExpired, SessionPasswordNeeded,
    ))


def test_required_message_and_name_api_is_available():
    assert callable(Message.download)
    assert callable(Message.edit_text)
    assert Chat(id=1, first_name="Test", last_name="User").full_name == "Test User"
    assert User(id=1, first_name="Test", last_name="User").full_name == "Test User"
