"""Persistent approvals and account disconnection, independent of Telegram FSM."""
import time
from uuid import UUID, uuid4

from sqlalchemy import delete, exists, or_, select, update

from db.account_operation_models import AccountOperation, ArchiveBlobCleanup, TransferAttachment, TransferRevision
from db.models import Account, TelegramApp
from db.personal_models import OwnerArchiveKey
from db.repositories.account_locks import lock_account, unique_account
from db.repositories.base import conflict_insert

TRANSFER_OPEN = {"pending", "needs_secret", "preparing"}


async def queue_blob_cleanup(session, owner_id, blob_key):
    if blob_key:
        await session.execute(conflict_insert(session, ArchiveBlobCleanup).values(
            owner_id=owner_id, blob_key=blob_key).on_conflict_do_nothing())


async def discard_staging(session, operation):
    for blob_key in await session.scalars(select(TransferAttachment.blob_key).where(
            TransferAttachment.operation_uuid == operation.uuid)):
        await queue_blob_cleanup(session, operation.actor_id, blob_key)
    await session.execute(delete(TransferAttachment).where(TransferAttachment.operation_uuid == operation.uuid))
    await session.execute(delete(TransferRevision).where(TransferRevision.operation_uuid == operation.uuid))


class AccountOperationsRepository:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    async def get(self, operation_id, actor_id):
        try:
            operation_id = UUID(str(operation_id))
        except (ValueError, TypeError):
            return None
        async with self._session_factory()() as session:
            return await session.scalar(select(AccountOperation).where(
                AccountOperation.uuid == operation_id,
                or_(AccountOperation.owner_id == actor_id, AccountOperation.actor_id == actor_id)))

    async def self_accounts(self, user_id):
        async with self._session_factory()() as session:
            return list((await session.scalars(select(Account).where(Account.user_id == user_id).order_by(Account.uuid))).all())

    async def has_limited_access(self, user_id):
        async with self._session_factory()() as session:
            return bool(await session.scalar(select(exists().where(Account.user_id == user_id)))) or bool(
                await session.scalar(select(exists().where(
                    AccountOperation.owner_id == user_id, AccountOperation.kind == "transfer",
                    AccountOperation.status.in_(TRANSFER_OPEN)))))

    async def request_transfer(self, account_id, actor_id, profile_id):
        async with self._session_factory()() as session, session.begin():
            account = await session.get(Account, UUID(str(account_id)))
            if account is None or account.user_id != actor_id or account.admin_id == actor_id:
                raise PermissionError("Only the connected account can request a transfer to itself")
            await lock_account(session, account.user_id)
            account = await unique_account(session, account.user_id)
            if account is None or account.user_id != actor_id or account.admin_id == actor_id:
                raise PermissionError("Account ownership has changed")
            profile = await session.get(TelegramApp, UUID(str(profile_id)))
            if profile is None or profile.user_id != actor_id:
                raise PermissionError("Target API profile is not owned by requester")
            if await session.get(OwnerArchiveKey, actor_id) is None:
                raise PermissionError("Set up a personal secret before requesting a transfer")
            current = await session.scalar(select(AccountOperation).where(AccountOperation.active_account_id == account.user_id))
            if current:
                if current.kind == "transfer" and current.actor_id == actor_id:
                    return current
                raise ValueError("Another account action is already running")
            now = int(time.time())
            operation = AccountOperation(account_uuid=account.uuid, account_user_id=account.user_id,
                owner_id=account.admin_id, actor_id=actor_id, target_app_uuid=profile.uuid,
                kind="transfer", status="pending", active_account_id=account.user_id,
                created_at=now, updated_at=now)
            session.add(operation)
            return operation

    async def request_delete(self, account_id, actor_id):
        async with self._session_factory()() as session, session.begin():
            account = await session.get(Account, UUID(str(account_id)))
            if account is None or actor_id not in {account.admin_id, account.user_id}:
                raise PermissionError("Account is not accessible")
            current = await session.scalar(select(AccountOperation).where(
                AccountOperation.account_uuid == account.uuid, AccountOperation.actor_id == actor_id,
                AccountOperation.kind == "delete", AccountOperation.status == "confirm_delete"))
            if current:
                return current
            now = int(time.time())
            operation = AccountOperation(account_uuid=account.uuid, account_user_id=account.user_id,
                owner_id=account.admin_id, actor_id=actor_id, kind="delete", status="confirm_delete",
                created_at=now, updated_at=now)
            session.add(operation)
            return operation

    async def confirm_delete(self, operation_id, actor_id):
        async with self._session_factory()() as session, session.begin():
            operation = await session.get(AccountOperation, UUID(str(operation_id)))
            if operation is None or operation.kind != "delete" or operation.actor_id != actor_id:
                raise PermissionError("Delete confirmation is not accessible")
            await lock_account(session, operation.account_user_id)
            account = await session.get(Account, operation.account_uuid, populate_existing=True)
            if operation.status in {"deleting", "removing_session", "complete"}:
                return operation
            if operation.status != "confirm_delete" or account is None or actor_id not in {account.admin_id, account.user_id}:
                raise PermissionError("Account ownership has changed")
            # Stopping one number-based session must never stop another legacy owner.
            await unique_account(session, account.user_id)
            active = await session.scalar(select(AccountOperation).where(AccountOperation.active_account_id == account.user_id))
            if active and active.uuid != operation.uuid:
                if active.kind != "transfer":
                    return active
                active.status, active.active_account_id, active.run_token = "cancelled", None, None
                active.owner_notified = active.result_notified = False
                active.notify_after, active.updated_at = 0, int(time.time())
                await discard_staging(session, active)
                await session.flush()
            operation.status, operation.active_account_id = "deleting", account.user_id
            operation.owner_id, operation.updated_at = account.admin_id, int(time.time())
            operation.session_number = account.number
            account.is_active = 0
            return operation

    async def reject(self, operation_id, actor_id):
        async with self._session_factory()() as session, session.begin():
            operation = await session.get(AccountOperation, UUID(str(operation_id)))
            if operation is None or actor_id not in {operation.owner_id, operation.actor_id}:
                raise PermissionError("Request is not accessible")
            if operation.kind == "delete" and actor_id != operation.actor_id:
                raise PermissionError("Only the requester can cancel deletion")
            await lock_account(session, operation.account_user_id)
            await session.refresh(operation)
            if operation.status not in {"pending", "needs_secret", "confirm_delete"}:
                return operation
            operation.status = "rejected" if actor_id == operation.owner_id else "cancelled"
            operation.active_account_id, operation.run_token = None, None
            operation.updated_at = int(time.time())
            operation.owner_notified = operation.result_notified = False
            operation.notify_after = 0
            await discard_staging(session, operation)
            return operation

    async def start_transfer(self, operation_id, owner_id):
        async with self._session_factory()() as session, session.begin():
            operation = await session.get(AccountOperation, UUID(str(operation_id)))
            if operation is None or operation.kind != "transfer" or operation.owner_id != owner_id:
                raise PermissionError("Only the current owner can approve this request")
            await lock_account(session, operation.account_user_id)
            await session.refresh(operation)
            if operation.status not in {"pending", "needs_secret"}:
                return None
            account = await unique_account(session, operation.account_user_id)
            profile = await session.get(TelegramApp, operation.target_app_uuid)
            if (account is None or account.uuid != operation.account_uuid or account.admin_id != owner_id
                    or profile is None or profile.user_id != operation.actor_id):
                raise PermissionError("Account or target profile has changed")
            if await session.get(OwnerArchiveKey, operation.actor_id) is None:
                raise PermissionError("Target archive key is missing")
            operation.status, operation.run_token = "preparing", uuid4()
            operation.updated_at, operation.last_error = int(time.time()), None
            return operation

    async def pause(self, operation_id, run_token, error_type):
        async with self._session_factory()() as session, session.begin():
            operation = await session.get(AccountOperation, operation_id)
            if operation is None:
                return
            await lock_account(session, operation.account_user_id)
            await session.refresh(operation)
            if operation.status != "preparing" or operation.run_token != run_token:
                return
            account = await session.get(Account, operation.account_uuid)
            profile = await session.get(TelegramApp, operation.target_app_uuid)
            if (account is None or account.admin_id != operation.owner_id or profile is None
                    or profile.user_id != operation.actor_id):
                operation.status, operation.active_account_id = "cancelled", None
                await discard_staging(session, operation)
            else:
                operation.status = "needs_secret"
            operation.run_token = None
            operation.owner_notified = operation.result_notified = False
            operation.notify_after, operation.updated_at, operation.last_error = 0, int(time.time()), error_type

    async def recover_interrupted(self):
        # A bot instance owns its in-memory key tasks; startup never resurrects a key.
        async with self._session_factory()() as session, session.begin():
            await session.execute(update(AccountOperation).where(AccountOperation.status == "preparing").values(
                status="needs_secret", run_token=None, owner_notified=False, notify_after=0, last_error="ProcessRestart",
                updated_at=int(time.time())))
            await session.execute(update(AccountOperation).where(AccountOperation.status == "activating").values(run_token=None))

    async def claim_activation(self, operation_id):
        async with self._session_factory()() as session, session.begin():
            return (await session.execute(update(AccountOperation).where(AccountOperation.uuid == operation_id,
                AccountOperation.status == "activating", AccountOperation.run_token.is_(None)).values(
                    run_token=uuid4()).returning(AccountOperation))).scalar_one_or_none()

    async def finish_transfer(self, operation_id, run_token, error_type=None):
        async with self._session_factory()() as session, session.begin():
            await session.execute(update(AccountOperation).where(AccountOperation.uuid == operation_id,
                AccountOperation.status == "activating", AccountOperation.run_token == run_token).values(
                    status="complete", run_token=None, last_error=error_type, owner_notified=False,
                    result_notified=False, notify_after=0, updated_at=int(time.time())))

    async def deleting(self):
        async with self._session_factory()() as session:
            return list((await session.scalars(select(AccountOperation).where(
                AccountOperation.status.in_({"deleting", "removing_session"})))).all())

    async def remove_connection(self, operation_id):
        async with self._session_factory()() as session, session.begin():
            operation = await session.get(AccountOperation, operation_id)
            if operation is None or operation.status != "deleting":
                return False
            await lock_account(session, operation.account_user_id)
            await session.refresh(operation)
            if operation.status != "deleting":
                return False
            # Archive ownership, ciphertext, revisions and media remain untouched.
            await session.execute(delete(Account).where(Account.uuid == operation.account_uuid))
            operation.status = "removing_session"
            operation.updated_at = int(time.time())
            return True

    async def finish_delete(self, operation_id):
        async with self._session_factory()() as session, session.begin():
            await session.execute(update(AccountOperation).where(AccountOperation.uuid == operation_id,
                AccountOperation.status == "removing_session").values(status="complete", active_account_id=None,
                    owner_notified=False, result_notified=False, notify_after=0, updated_at=int(time.time())))

    async def is_busy(self, account_user_id):
        async with self._session_factory()() as session:
            return bool(await session.scalar(select(exists().where(AccountOperation.active_account_id == account_user_id,
                AccountOperation.status.in_({"deleting", "removing_session"})))))
