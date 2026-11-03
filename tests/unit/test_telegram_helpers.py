"""
Tests for utils/telegram_helpers.py
"""
from __future__ import annotations

import types

from utils.telegram_helpers import is_bot_or_channel


def test_is_bot_or_channel_detects_bot():
    chat = types.SimpleNamespace(type="bot")
    assert is_bot_or_channel(chat) is True


def test_is_bot_or_channel_detects_channel():
    chat = types.SimpleNamespace(type="channel")
    assert is_bot_or_channel(chat) is True


def test_is_bot_or_channel_detects_supergroup():
    chat = types.SimpleNamespace(type="supergroup")
    assert is_bot_or_channel(chat) is False


def test_is_bot_or_channel_detects_private():
    chat = types.SimpleNamespace(type="private")
    assert is_bot_or_channel(chat) is False


def test_is_bot_or_channel_case_insensitive():
    chat = types.SimpleNamespace(type="BOT")
    assert is_bot_or_channel(chat) is True


def test_is_bot_or_channel_partial_match():
    # Ensure "bot" substring matches even in compound types
    chat = types.SimpleNamespace(type="some_bot_type")
    assert is_bot_or_channel(chat) is True


def test_is_bot_or_channel_no_type_attribute():
    chat = types.SimpleNamespace()
    assert is_bot_or_channel(chat) is False


def test_is_bot_or_channel_none_type():
    chat = types.SimpleNamespace(type=None)
    assert is_bot_or_channel(chat) is False
