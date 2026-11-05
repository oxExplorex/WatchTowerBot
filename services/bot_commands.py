"""Publish the single command; control actions live in keyboards."""
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeDefault

from core.logging import bot_logger
from data.texts.common import START_COMMAND_DESCRIPTION


async def register_bot_commands(bot):
    commands = [BotCommand(command="start", description=START_COMMAND_DESCRIPTION)]
    for scope in (BotCommandScopeDefault(), BotCommandScopeAllPrivateChats()):
        try:
            await bot.set_my_commands(commands, scope=scope)
        except Exception as exc:
            bot_logger.warning("Command menu update failed: scope=%s error=%s", scope.type, type(exc).__name__)
