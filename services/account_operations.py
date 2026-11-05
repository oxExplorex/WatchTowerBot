"""Run durable account actions; private keys exist only in a live transfer task."""
import asyncio
import time

from sqlalchemy import delete, exists, or_, select, update

from core.account_runtime import account_guard
from core.async_tools import create_logged_task
from core.logging import bot_logger
from core.media_store import MediaStore
from core.session_files import remove_account_session_files
from core.session_runtime import get_client_by_number, start_client, stop_and_remove_session
from core.thread_tools import run_blocking
from db.account_operation_models import AccountOperation, ArchiveBlobCleanup, TransferAttachment
from db.media_models import MessageAttachment
from db.models import Account
from db.repositories.account_operations_repo import AccountOperationsRepository
from db.repositories.personal_repo import lock_owner
from db.session import get_session_factory
from data.texts import account_ownership as text
from services.account_transfer import prepare_batch, publish
from utils.crypto_store import decrypt_text

repository = AccountOperationsRepository(get_session_factory)


async def start_transfer(bot, operation_id, owner_id, private_key):
    operation = await repository.start_transfer(operation_id, owner_id)
    if operation is None:
        return False
    create_logged_task(_transfer(bot, operation, private_key), name=f"account_transfer:{operation.uuid}")
    return True


async def _restart_transferred_client(operation, client):
    from db.main import get_account_uuid, get_app_tg_uuid
    from loader import session_manager

    async with get_session_factory()() as session:
        account = await session.get(Account, operation.account_uuid)
    if account is None:
        return
    number = decrypt_text(account.number)
    async with account_guard(("session", number)):
        account = await get_account_uuid(operation.account_uuid, operation.actor_id)
        if account is None or not account.is_active:
            return
        app = await get_app_tg_uuid(account.app_tg, operation.actor_id)
        if app is None:
            raise RuntimeError("Destination API profile disappeared")
        current = await get_client_by_number(number)
        if current is not None:
            client = current
        if client is None:
            from pyrogram import Client
            from core.client_handlers import register_client_handlers

            client = Client(name=f"data/session/{account.number}", phone_number=account.number,
                            api_id=app.app_id, api_hash=app.api_hash)
            register_client_handlers([client])
        else:
            client.api_id, client.api_hash = app.app_id, app.api_hash
        await session_manager.add(client)
        await start_client(client)


async def _transfer(bot, operation, private_key):
    client, stopped, published = None, False, False
    try:
        store = MediaStore.from_environment()
        async with get_session_factory()() as session:
            account = await session.get(Account, operation.account_uuid)
            if account is None:
                raise RuntimeError("Account disappeared")
            number = decrypt_text(account.number)
        while True:
            ready = await prepare_batch(get_session_factory, operation.uuid, operation.run_token, private_key, store)
            if ready is None:
                return
            if ready:
                async with account_guard(("session", number)):
                    if not stopped:
                        client = await get_client_by_number(number)
                        await stop_and_remove_session(number)
                        stopped = True
                    async with account_guard(operation.account_user_id):
                        result = await publish(get_session_factory, operation.uuid, operation.run_token)
                if result is None:
                    return
                if result:
                    published = True
                    break
            await asyncio.sleep(0.1)
        await _activate(operation, client)
        from services.notification_topics import schedule_topic_preparation

        schedule_topic_preparation(bot, operation.actor_id, operation.account_user_id)
    except BaseException as error:
        await repository.pause(operation.uuid, operation.run_token, type(error).__name__)
        if stopped and not published and client is not None and not isinstance(error, asyncio.CancelledError):
            try:
                from loader import session_manager
                from db.main import get_account_uuid

                async with account_guard(("session", number)):
                    current = await get_account_uuid(operation.account_uuid, operation.owner_id)
                    if current is not None and current.is_active:
                        await session_manager.add(client)
                        await start_client(client)
            except Exception as restart_error:
                bot_logger.warning("Original session restart deferred: %s", type(restart_error).__name__)
        if isinstance(error, asyncio.CancelledError):
            raise
        bot_logger.warning("Account transfer paused: %s", type(error).__name__)
    finally:
        private_key = None


async def _activate(operation, client=None):
    error_type = None
    try:
        await _restart_transferred_client(operation, client)
    except Exception as error:
        error_type = type(error).__name__
        bot_logger.warning("Transferred session startup deferred: %s", error_type)
    await repository.finish_transfer(operation.uuid, operation.run_token, error_type)


async def resume_activations():
    async with get_session_factory()() as session:
        ids = (await session.scalars(select(AccountOperation.uuid).where(
            AccountOperation.status == "activating", AccountOperation.run_token.is_(None)))).all()
    for operation_id in ids:
        operation = await repository.claim_activation(operation_id)
        if operation:
            await _activate(operation)


async def cleanup_blobs(store, *, limit=100):
    async with get_session_factory()() as session:
        items = (await session.scalars(select(ArchiveBlobCleanup).limit(limit))).all()
    for item in items:
        async with get_session_factory()() as session, session.begin():
            await lock_owner(session, item.owner_id)
            if await session.scalar(select(exists().where(MessageAttachment.owner_id == item.owner_id,
                    MessageAttachment.status == "downloading", MessageAttachment.lease_until > int(time.time())))):
                continue
            referenced = await session.scalar(select(exists().where(MessageAttachment.owner_id == item.owner_id,
                MessageAttachment.blob_key == item.blob_key)))
            staged = await session.scalar(select(exists(select(TransferAttachment.attachment_uuid).join(AccountOperation).where(
                AccountOperation.actor_id == item.owner_id, TransferAttachment.blob_key == item.blob_key))))
            if not referenced and not staged:
                await run_blocking(store.remove_blob, item.owner_id, item.blob_key)
            await session.execute(delete(ArchiveBlobCleanup).where(
                ArchiveBlobCleanup.owner_id == item.owner_id, ArchiveBlobCleanup.blob_key == item.blob_key))


async def process_deletions():
    for operation in await repository.deleting():
        try:
            await process_deletion(operation)
        except Exception as error:
            bot_logger.warning("Account disconnection deferred: operation=%s error=%s", operation.uuid, type(error).__name__)


def schedule_deletion(operation):
    create_logged_task(process_deletion(operation), name=f"account_delete:{operation.uuid}")


async def process_deletion(operation):
    number = decrypt_text(operation.session_number) if operation.session_number else None
    async with account_guard(("session", number)):
        # The periodic worker and the immediate task may see the same request.
        operation = await repository.get(operation.uuid, operation.actor_id)
        if operation is None or operation.status not in {"deleting", "removing_session"}:
            return
        if number:
            await stop_and_remove_session(number)
        async with account_guard(operation.account_user_id):
            if operation.status == "deleting" and not await repository.remove_connection(operation.uuid):
                return
            if number:
                await run_blocking(remove_account_session_files, number, strict=True)
            await repository.finish_delete(operation.uuid)


async def notify_operations(bot):
    from keyboards.inline.account_ownership import approval_keyboard

    async with get_session_factory()() as session:
        operations = (await session.scalars(select(AccountOperation).where(
            AccountOperation.notify_after <= int(time.time()),
            or_((AccountOperation.status.in_({"pending", "needs_secret"})) & (AccountOperation.owner_notified == False),
                (AccountOperation.status.in_({"complete", "rejected", "cancelled"})) &
                or_(AccountOperation.owner_notified == False, AccountOperation.result_notified == False))
        ).order_by(AccountOperation.updated_at).limit(50))).all()
    for operation in operations:
        if operation.kind == "transfer" and operation.status in {"pending", "needs_secret"}:
            if operation.owner_notified:
                continue
            template = text.REQUEST if operation.status == "pending" else text.RESUME
            targets = [(operation.owner_id, "owner_notified")]
            keyboard = approval_keyboard(operation)
        else:
            template = (text.DELETE_FULL_DONE if operation.kind == "delete_full" and operation.status == "complete" else
                        text.DELETE_DONE if operation.kind == "delete" and operation.status == "complete" else
                        text.TRANSFER_DONE if operation.status == "complete" else text.REJECTED)
            if operation.kind == "transfer" and operation.last_error and operation.status == "complete":
                template += text.RUNTIME_WARNING
            targets = [(operation.owner_id, "owner_notified"), (operation.actor_id, "result_notified")]
            keyboard = None
        failed = False
        recipients = {}
        for recipient, field in targets:
            if not getattr(operation, field):
                recipients.setdefault(recipient, []).append(field)
        for recipient, fields in recipients.items():
            try:
                await bot.send_message(recipient, template.format(actor_id=operation.actor_id,
                    account_id=operation.account_user_id), parse_mode="HTML", reply_markup=keyboard)
            except Exception as error:
                bot_logger.warning("Account action notification deferred: %s", type(error).__name__)
                failed = True
            else:
                async with get_session_factory()() as session, session.begin():
                    await session.execute(update(AccountOperation).where(AccountOperation.uuid == operation.uuid,
                        AccountOperation.status == operation.status).values(**{field: True for field in fields}))
        if failed:
            async with get_session_factory()() as session, session.begin():
                await session.execute(update(AccountOperation).where(AccountOperation.uuid == operation.uuid,
                    AccountOperation.status == operation.status).values(
                    notify_after=int(time.time()) + 600))


async def run_account_operations(bot):
    store = MediaStore.from_environment()
    while True:
        try:
            await resume_activations()
            await process_deletions()
            await cleanup_blobs(store)
            await notify_operations(bot)
        except Exception as error:
            bot_logger.warning("Account actions deferred: %s", type(error).__name__)
        await asyncio.sleep(5)
