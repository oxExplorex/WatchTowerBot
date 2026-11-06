"""A scoped encrypted snapshot in one ZIP, delivered by a bot-only MTProto client."""
from pathlib import Path
import asyncio
from html import escape
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
from db.models import Account
from db.history_models import HistoryChat, HistoryRange
from services.backup_snapshot import create_backup
from services.notification_topics import delivery
from data.texts import backups as text

PAGE_SIZE = 8
MAX_ZIP_SIZE = 1900 * 1024 * 1024
CONNECT_TIMEOUT = 90


class DumpTooLarge(InvalidBackup):
    pass


async def chat_history_status(owner_id, account_id, chat_id, *, session_factory):
    async with session_factory()() as session:
        progress = await session.scalar(select(HistoryChat).join(Account, Account.uuid == HistoryChat.account_uuid).where(
            Account.admin_id == owner_id, Account.user_id == account_id, HistoryChat.chat_id == chat_id))
        if progress is None:
            return text.DUMP_HISTORY_UNKNOWN
        ranges = list((await session.execute(select(HistoryRange.low_id, HistoryRange.high_id).where(
            HistoryRange.account_uuid == progress.account_uuid, HistoryRange.chat_id == chat_id)
            .order_by(HistoryRange.high_id.desc()).limit(4))).all())
        checked = ", ".join(f"{low}–{high}" for low, high in ranges[:3]) or text.DUMP_HISTORY_NO_RANGES
        if len(ranges) > 3:
            checked += ", …"
        return text.DUMP_HISTORY_STATUS.format(
            start=text.DUMP_HISTORY_REACHED if progress.reached_start else text.DUMP_HISTORY_PENDING,
            checked=checked, error=escape(progress.last_error) if progress.last_error else text.DUMP_HISTORY_NO_ERROR)


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
    bot_logger.info("Chat dump ZIP ready: owner_id=%s account_id=%s chat_id=%s bytes=%s messages=%s revisions=%s media=%s avatars=%s",
                    owner_id, account_user_id, chat_id, target.stat().st_size,
                    counts["messages"], counts["revisions"], counts["media"], counts["avatars"])
    return target, counts


async def create_all_chats_dump(owner_id, root, *, session_factory, store):
    root = Path(root)
    paths, counts = await create_backup(owner_id, root / "parts", uuid4().hex,
        session_factory=session_factory, store=store)
    target = root / "all_private_chats.zip"
    await run_blocking(_make_zip, paths, target)
    bot_logger.info("All chats dump ZIP ready: owner_id=%s bytes=%s messages=%s revisions=%s media=%s avatars=%s",
                    owner_id, target.stat().st_size, counts["messages"], counts["revisions"],
                    counts["media"], counts["avatars"])
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
            if kwargs.get("message_thread_id") is not None:
                if result is None:
                    raise RuntimeError("MTProto upload returned no message")
                # Use Bot API for the final private-topic assignment. The ciphertext
                # is copied on Telegram's servers, with no second upload/download.
                copied = await bot.copy_message(from_chat_id=owner_id, message_id=result.id,
                    caption=caption, parse_mode="HTML", **kwargs)
                try:
                    await bot.delete_message(chat_id=owner_id, message_id=result.id)
                except Exception as error:
                    bot_logger.warning("Dump staging message cleanup failed: owner_id=%s error=%s",
                                       owner_id, type(error).__name__)
                result = copied
            bot_logger.info("Chat dump transport: owner_id=%s stage=sent", owner_id)
            return result
        return await delivery(bot).send(send, owner_id, "backups", text.TOPIC_TITLE)
    finally:
        await close_partial_client(client)
