"""A scoped encrypted snapshot in one ZIP, delivered by a bot-only MTProto client."""
from pathlib import Path
import asyncio
import zipfile
from uuid import uuid4

from pyrogram import Client
from pyrogram.enums import ParseMode
from sqlalchemy import select

from core.backup_format import InvalidBackup
from core.logging import bot_logger
from core.session_runtime import close_partial_client
from core.thread_tools import run_blocking
from db.message_models import StoredMessage
from services.backup_snapshot import create_backup
from services.notification_topics import delivery
from data.texts import backups as text

PAGE_SIZE = 8
MAX_ZIP_SIZE = 1900 * 1024 * 1024
CONNECT_TIMEOUT = 90


class DumpTooLarge(InvalidBackup):
    pass


async def chat_accounts(owner_id, chat_id, *, session_factory, page=0):
    if not 0 <= page <= 100000 or not 0 < chat_id < 2**63:
        raise InvalidBackup("Invalid chat selection")
    async with session_factory()() as session:
        return list(await session.scalars(select(StoredMessage.account_user_id).where(
            StoredMessage.owner_id == owner_id, StoredMessage.chat_id == chat_id,
            StoredMessage.channel_namespace == False).distinct().order_by(StoredMessage.account_user_id)
            .offset(page * PAGE_SIZE).limit(PAGE_SIZE + 1)))


def _make_zip(paths, target):
    if sum(path.stat().st_size for path in paths) > MAX_ZIP_SIZE:
        raise DumpTooLarge("Dump exceeds transport limit")
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for path in paths:
            archive.write(path, arcname=path.name)
    if target.stat().st_size > MAX_ZIP_SIZE:
        raise DumpTooLarge("Dump exceeds transport limit")


async def create_chat_dump(owner_id, account_user_id, chat_id, root, *, session_factory, store):
    async with session_factory()() as session:
        allowed = await session.scalar(select(StoredMessage.uuid).where(
            StoredMessage.owner_id == owner_id, StoredMessage.account_user_id == account_user_id,
            StoredMessage.chat_id == chat_id, StoredMessage.channel_namespace == False).limit(1))
    if allowed is None:
        raise InvalidBackup("Chat not present in owner's archive")
    root = Path(root)
    paths, counts = await create_backup(owner_id, root / "parts", uuid4().hex,
        session_factory=session_factory, store=store, account_user_id=account_user_id, chat_id=chat_id)
    target = root / f"chat_{chat_id}_account_{account_user_id}.zip"
    await run_blocking(_make_zip, paths, target)
    bot_logger.info("Chat dump ZIP ready: owner_id=%s account_id=%s chat_id=%s bytes=%s messages=%s revisions=%s media=%s",
                    owner_id, account_user_id, chat_id, target.stat().st_size,
                    counts["messages"], counts["revisions"], counts["media"])
    return target, counts


async def send_chat_dump(bot, owner_id, path, caption, app, *, client_factory=Client):
    if app.user_id != owner_id:
        raise InvalidBackup("Foreign API profile")
    if Path(path).stat().st_size > MAX_ZIP_SIZE:
        raise DumpTooLarge("Dump exceeds transport limit")
    client = client_factory(name=f"backup_bot_{bot.id}_{owner_id}", api_id=app.app_id, api_hash=app.api_hash,
                            bot_token=bot.token, in_memory=True, no_updates=True)
    try:
        bot_logger.info("Chat dump transport: owner_id=%s stage=connect", owner_id)
        async with asyncio.timeout(CONNECT_TIMEOUT):
            await client.start()
        bot_logger.info("Chat dump transport: owner_id=%s stage=connected", owner_id)
        async def send(**kwargs):
            bot_logger.info("Chat dump transport: owner_id=%s stage=upload", owner_id)
            result = await client.send_document(document=str(path), caption=caption, parse_mode=ParseMode.HTML, **kwargs)
            bot_logger.info("Chat dump transport: owner_id=%s stage=sent", owner_id)
            return result
        return await delivery(bot).send(send, owner_id, "backups", text.TOPIC_TITLE)
    finally:
        await close_partial_client(client)
