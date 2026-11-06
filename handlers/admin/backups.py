"""Short file/secret dialogs; expensive work runs outside FSM event isolation."""
import asyncio
from tempfile import TemporaryDirectory
from uuid import uuid4

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import FSInputFile, ForceReply

from callbacks import backups as callback
from core.async_tools import create_logged_task
from core.logging import bot_logger
from core.media_store import MediaStore
from core.thread_tools import run_blocking
from data.texts import backups as text
from db.main import get_configured_admin_ids
from db.session import get_session_factory
from filters.all_filters import IsAdmin, IsPrivate
from handlers.admin.personal_secret import PersonalSecretDialog
from keyboards.inline.backups import backup_keyboard
from services.backup_snapshot import create_backup
from services.backup_restore import prepare_backup, restore_backup
from services import backup_uploads as uploads
from services.notification_topics import delivery
from states.backups import IMPORT_FILES, IMPORT_SECRET, IMPORT_STATES
from states.backups import DUMP_CHAT_ID
from keyboards.inline.backups import dump_accounts_keyboard
from services.chat_dump import PAGE_SIZE, DumpTooLarge, chat_accounts, create_chat_dump, send_chat_dump
from utils.panel import edit_input_panel, edit_panel, remember_panel

router = Router(name=__name__)
_busy = set()
_crypto_limit = asyncio.Semaphore(1)


async def _notice(bot, owner, message, **kwargs):
    return await delivery(bot).send(bot.send_message, owner, "backups", text.TOPIC_TITLE,
                                   text=message, parse_mode="HTML", **kwargs)


async def _export(bot, owner):
    try:
        uploads.BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="export_", dir=uploads.BACKUP_ROOT) as root:
            files, counts = await create_backup(owner, root, uuid4().hex,
                session_factory=get_session_factory, store=MediaStore.from_environment())
            for index, path in enumerate(files, 1):
                await delivery(bot).send(bot.send_document, owner, "backups", text.TOPIC_TITLE,
                    document=FSInputFile(path), caption=text.PART_CAPTION.format(index=index, total=len(files), **counts),
                    parse_mode="HTML", request_timeout=180)
                if index < len(files):
                    await asyncio.sleep(1)
            await _notice(bot, owner, text.SENT)
    except Exception as error:
        bot_logger.warning("Backup export failed: owner_id=%s error=%s", owner, type(error).__name__)
        await _notice(bot, owner, text.FAILED)
    finally:
        _busy.discard(owner)


async def _restore(bot, owner, identity, total, secret):
    try:
        paths = uploads.collect_parts(owner, identity, total)
        with TemporaryDirectory(prefix="restore_", dir=uploads.BACKUP_ROOT) as root:
            async with _crypto_limit:
                prepared = await run_blocking(prepare_backup, paths, root, owner, secret)
                counts = await restore_backup(prepared, owner, secret,
                    session_factory=get_session_factory, store=MediaStore.from_environment())
            await _notice(bot, owner, text.RESTORED.format(**counts))
            await run_blocking(uploads.discard_upload, owner, identity)
    except Exception as error:
        # Never include input, exception text, traceback locals or Update in this log.
        bot_logger.warning("Backup import failed: owner_id=%s error=%s", owner, type(error).__name__)
        await _notice(bot, owner, text.FAILED)
    finally:
        _busy.discard(owner)


@router.callback_query(IsPrivate(), IsAdmin(), F.data.in_({callback.MENU, callback.CREATE, callback.IMPORT, callback.RESTORE, callback.DUMP}), StateFilter("*"))
async def backup_action(call, state):
    owner = call.from_user.id
    if owner not in get_configured_admin_ids():
        await call.answer(text.FORBIDDEN, show_alert=True)
        return
    if owner in _busy:
        await call.answer(text.BUSY, show_alert=True)
        return
    if call.data == callback.RESTORE:
        data = await state.get_data()
        try:
            uploads.collect_parts(owner, data["backup_identity"], data["backup_total"])
        except (KeyError, OSError, ValueError):
            await call.answer(text.MISSING_PARTS, show_alert=True)
            return
        await call.answer()
        await state.set_state(IMPORT_SECRET)
        await _notice(call.bot, owner, text.SECRET_PROMPT, reply_markup=ForceReply(selective=True))
        return
    await call.answer()
    await state.clear()
    await remember_panel(state, call.message)
    if call.data == callback.DUMP:
        await state.set_state(DUMP_CHAT_ID)
        await edit_panel(call.message, text.DUMP_PROMPT, backup_keyboard(uploading=True))
    elif call.data == callback.IMPORT:
        await state.set_state(IMPORT_FILES)
        await edit_panel(call.message, text.UPLOAD_PROMPT, backup_keyboard(uploading=True))
    elif call.data == callback.CREATE:
        _busy.add(owner)
        create_logged_task(_export(call.bot, owner), name=f"backup-export:{owner}")
        await _notice(call.bot, owner, text.CREATING)
    else:
        await edit_panel(call.message, text.MENU, backup_keyboard())


@router.message(IsPrivate(), IsAdmin(), StateFilter(IMPORT_FILES), F.document)
async def backup_part(message, state):
    if message.from_user.id not in get_configured_admin_ids():
        return
    try:
        identity, received, total = await uploads.receive_part(message.bot, message.from_user.id, message.document)
    except Exception as error:
        bot_logger.warning("Backup part rejected: owner_id=%s error=%s", message.from_user.id, type(error).__name__)
        await edit_input_panel(message, state, text.UPLOAD_FAILED, backup_keyboard(uploading=True))
        return
    await state.update_data(backup_identity=identity, backup_total=total)
    await edit_input_panel(message, state, text.UPLOAD_PROGRESS.format(received=received, total=total),
                           backup_keyboard(uploading=True, complete=received == total))
    try:
        await message.delete()
    except Exception:
        pass


@router.message(IsPrivate(), IsAdmin(), StateFilter(IMPORT_SECRET), F.text)
async def backup_secret(message, state):
    if message.from_user.id not in get_configured_admin_ids():
        return
    if not await PersonalSecretDialog.delete_input(message):
        await _notice(message.bot, message.from_user.id, text.DELETE_FAILED)
        return
    data = await state.get_data()
    await state.clear()
    owner = message.from_user.id
    if owner in _busy or "backup_identity" not in data:
        await _notice(message.bot, owner, text.BUSY if owner in _busy else text.SECRET_INTERRUPTED)
        return
    _busy.add(owner)
    create_logged_task(_restore(message.bot, owner, data["backup_identity"], data["backup_total"], message.text),
                       name=f"backup-import:{owner}")
    await _notice(message.bot, owner, text.RESTORING)


@router.edited_message(IsPrivate(), IsAdmin(), StateFilter(IMPORT_SECRET))
async def edited_backup_secret(message):
    await PersonalSecretDialog.delete_input(message)


async def _dump(bot, owner, account_id, chat_id, *, progress=None):
    stage = "profile"
    async def update(status, *, done=False):
        if progress is not None:
            await progress(status, done=done)
    try:
        bot_logger.info("Chat dump stage: owner_id=%s account_id=%s chat_id=%s stage=%s", owner, account_id, chat_id, stage)
        from db.main import get_app_tg_user_id
        apps, _ = await get_app_tg_user_id(owner)
        if not apps:
            await update(text.DUMP_NEEDS_APP, done=True)
            await _notice(bot, owner, text.DUMP_NEEDS_APP)
            return
        uploads.BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="chat_dump_", dir=uploads.BACKUP_ROOT) as root:
            stage = "build_zip"
            bot_logger.info("Chat dump stage: owner_id=%s account_id=%s chat_id=%s stage=%s", owner, account_id, chat_id, stage)
            path, counts = await create_chat_dump(owner, account_id, chat_id, root,
                session_factory=get_session_factory, store=MediaStore.from_environment())
            await update(text.DUMP_SENDING.format(**counts))
            stage = "delivery"
            await send_chat_dump(bot, owner, path,
                text.DUMP_CAPTION.format(chat_id=chat_id, account_user_id=account_id, **counts), apps[0])
            await update(text.DUMP_DONE.format(chat_id=chat_id), done=True)
            bot_logger.info("Chat dump completed: owner_id=%s account_id=%s chat_id=%s", owner, account_id, chat_id)
    except asyncio.CancelledError:
        await update(text.DUMP_INTERRUPTED, done=True)
        raise
    except DumpTooLarge:
        await update(text.DUMP_TOO_LARGE, done=True)
        await _notice(bot, owner, text.DUMP_TOO_LARGE)
    except Exception as error:
        bot_logger.warning("Chat dump failed: owner_id=%s account_id=%s chat_id=%s stage=%s error=%s",
                           owner, account_id, chat_id, stage, type(error).__name__)
        await update(text.DUMP_FAILED, done=True)
        await _notice(bot, owner, text.DUMP_FAILED)
    finally:
        _busy.discard(owner)


async def _start_dump(message, state, owner, account_id, chat_id):
    if owner in _busy:
        await edit_input_panel(message, state, text.BUSY, backup_keyboard(uploading=True))
        return
    data = await state.get_data()
    panel_id = data.get("panel_message_id", message.message_id)
    operation = uuid4().hex
    await state.clear()
    await state.update_data(panel_message_id=panel_id, dump_operation=operation)

    async def progress(status, *, done=False):
        # A completed background job must not replace a screen the user navigated to.
        current = await state.get_data()
        if current.get("dump_operation") != operation:
            return
        try:
            await edit_input_panel(message, state, status, backup_keyboard(uploading=not done))
            if done:
                await state.update_data(dump_operation=None)
        except Exception as error:
            bot_logger.warning("Dump panel update unavailable: owner_id=%s error=%s", owner, type(error).__name__)

    await progress(text.DUMP_BUILDING.format(chat_id=chat_id, account_id=account_id))
    _busy.add(owner)
    bot_logger.info("Chat dump requested: owner_id=%s account_id=%s chat_id=%s", owner, account_id, chat_id)
    create_logged_task(_dump(message.bot, owner, account_id, chat_id, progress=progress), name=f"chat-dump:{owner}")


async def _choose_dump(message, state, owner, chat_id, page=0):
    accounts = await chat_accounts(owner, chat_id, session_factory=get_session_factory, page=page)
    if not accounts:
        await edit_input_panel(message, state, text.DUMP_EMPTY, backup_keyboard())
    elif len(accounts) == 1 and page == 0:
        await _start_dump(message, state, owner, accounts[0], chat_id)
    else:
        await edit_input_panel(message, state, text.DUMP_ACCOUNTS,
            dump_accounts_keyboard(chat_id, accounts[:PAGE_SIZE], page, len(accounts) > PAGE_SIZE))


@router.message(IsPrivate(), IsAdmin(), StateFilter(DUMP_CHAT_ID), F.text)
async def dump_chat_id(message, state):
    if message.from_user.id not in get_configured_admin_ids():
        return
    raw = (message.text or "").strip()
    if not raw.isascii() or not raw.isdecimal() or len(raw) > 19 or not 0 < int(raw) < 2**63:
        await edit_input_panel(message, state, text.DUMP_INVALID, backup_keyboard(uploading=True))
        return
    await _choose_dump(message, state, message.from_user.id, int(raw))


@router.callback_query(IsPrivate(), IsAdmin(), F.data.startswith(callback.DUMP_SELECT) | F.data.startswith(callback.DUMP_PAGE), StateFilter("*"))
async def dump_selection(call, state):
    owner = call.from_user.id
    if owner not in get_configured_admin_ids():
        await call.answer(text.FORBIDDEN, show_alert=True)
        return
    if owner in _busy:
        await call.answer(text.BUSY, show_alert=True)
        return
    try:
        prefix, action, chat_id, value = call.data.split(":")
        if len(chat_id) > 19 or len(value) > 19:
            raise ValueError()
        chat_id, value = int(chat_id), int(value)
        if not 0 < chat_id < 2**63 or value < 0 or value >= 2**63:
            raise ValueError()
    except ValueError:
        await call.answer(text.DUMP_INVALID, show_alert=True)
        return
    await call.answer()
    await state.clear()
    await remember_panel(state, call.message)
    if action == "page":
        if value > 100000:
            return
        await _choose_dump(call.message, state, owner, chat_id, value)
    else:
        # Recheck scope inside create_chat_dump; forged/stale buttons cannot export another owner's records.
        await _start_dump(call.message, state, owner, value, chat_id)
