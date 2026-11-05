from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

@pytest.mark.asyncio
async def test_command_menu_only_publishes_start(offline_module):
    register_bot_commands = offline_module("services/bot_commands.py").register_bot_commands
    bot = SimpleNamespace(set_my_commands=AsyncMock())
    await register_bot_commands(bot)
    assert bot.set_my_commands.await_count == 2
    for call in bot.set_my_commands.await_args_list:
        assert [command.command for command in call.args[0]] == ["start"]


@pytest.mark.asyncio
async def test_command_menu_failure_does_not_block_other_scope_or_startup(offline_module):
    register_bot_commands = offline_module("services/bot_commands.py").register_bot_commands
    bot = SimpleNamespace(set_my_commands=AsyncMock(side_effect=[RuntimeError("offline"), True]))
    await register_bot_commands(bot)
    assert bot.set_my_commands.await_count == 2
