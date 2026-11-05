"""Secret setup and confirmation, invoked before ordinary update processing."""
import asyncio
from collections import OrderedDict
import time

from aiogram.types import ForceReply

from core.personal_crypto import InvalidSecret, create_key_bundle, normalize_secret, unlock_private_key
from core.thread_tools import run_blocking
from data.texts import personal_secret as texts
from data.texts.personal_secret import CONFIRM_PROMPT, INPUT_PROMPT
from db.repositories.personal_repo import PersonalKeyRepository
from db.session import get_session_factory
from keyboards.inline.personal_secret import cancel_keyboard, setup_keyboard
from states.personal_secret import PersonalSecret, SECRET_CONFIRM, SECRET_INPUT, SECRET_TRANSFER


class PersonalSecretDialog:
    def __init__(self, repository=None, authorize=None):
        self.repository = repository or PersonalKeyRepository(get_session_factory)
        self.authorize = authorize
        self._crypto_limit = asyncio.Semaphore(1)
        self._attempts = OrderedDict()

    async def _crypto(self, function, *args):
        async with self._crypto_limit:
            return await run_blocking(function, *args)

    def _blocked(self, owner_id):
        now = time.monotonic()
        attempts, until = self._attempts.get(owner_id, (0, now + 300))
        if until <= now:
            attempts, until = 0, now + 300
        self._attempts[owner_id] = (attempts, until)
        self._attempts.move_to_end(owner_id)
        if len(self._attempts) > 1024:
            self._attempts.popitem(last=False)
        return attempts >= 5

    def _failed(self, owner_id):
        count, until = self._attempts[owner_id]
        self._attempts[owner_id] = (count + 1, until)

    @staticmethod
    async def delete_input(message):
        try:
            await message.delete()
            return True
        except Exception:
            # Never forward an undeleted secret to ordinary handlers or error logs.
            await message.answer(texts.DELETE_FAILED)
            return False

    async def begin(self, message, state, *, verify=False, transfer_request=None):
        from utils.others import close_state_pyrogram_client

        await close_state_pyrogram_client(state)
        await state.clear()
        await state.update_data(secret_expires=int(time.time()) + 600)
        if transfer_request is not None:
            await state.update_data(transfer_request=str(transfer_request))
        await state.set_state(PersonalSecret.transfer if transfer_request is not None else
                              PersonalSecret.verify if verify else PersonalSecret.input)
        await message.answer(INPUT_PROMPT, protect_content=True, reply_markup=ForceReply(selective=True))
        await message.answer(texts.INPUT_CONTROLS, reply_markup=cancel_keyboard())

    async def handle_input(self, message, state, owner_id, key, current):
        if not await self.delete_input(message):
            return
        data = await state.get_data()
        if data.get("secret_expires", 0) < int(time.time()):
            await state.clear()
            await message.answer(texts.INPUT_EXPIRED, reply_markup=setup_keyboard() if key is None else None)
            return
        if self._blocked(owner_id):
            await message.answer(texts.TOO_MANY_ATTEMPTS)
            return
        try:
            secret = normalize_secret(message.text or "")
            if current == SECRET_INPUT:
                if key is not None:
                    await state.clear()
                    await message.answer(texts.ALREADY_CONFIGURED)
                    return
                bundle = await self._crypto(create_key_bundle, owner_id, secret)
                # Persistent FSM contains only a password-encrypted key bundle.
                await state.update_data(secret_bundle=bundle)
                await state.set_state(PersonalSecret.confirm)
                await message.answer(CONFIRM_PROMPT, protect_content=True, reply_markup=ForceReply(selective=True))
            else:
                bundle = data.get("secret_bundle") if current == SECRET_CONFIRM else key
                if bundle is None:
                    await state.clear()
                    await message.answer(texts.RESTART_SETUP, reply_markup=setup_keyboard())
                    return
                private = await self._crypto(unlock_private_key, owner_id, bundle, secret)
                if self.authorize is None:
                    from services.account_access import can_use_secret
                    permitted = await can_use_secret(owner_id)
                else:
                    permitted = await self.authorize(owner_id)
                if not permitted:
                    del private
                    await state.clear()
                    return
                if current == SECRET_TRANSFER:
                    from services.account_operations import start_transfer
                    from data.texts import account_ownership

                    started = await start_transfer(message.bot, data.get("transfer_request"), owner_id, private)
                    await state.clear()
                    await message.answer(account_ownership.STARTED if started else account_ownership.UNAVAILABLE)
                elif current == SECRET_CONFIRM:
                    if not await self.repository.install(owner_id, bundle):
                        await state.clear()
                        await message.answer(texts.SETUP_CONFLICT)
                        return
                    await state.clear()
                    await message.answer(texts.SETUP_COMPLETE)
                else:
                    await state.clear()
                    await state.update_data(personal_verified_until=int(time.time()) + 600)
                    await message.answer(texts.VERIFY_COMPLETE)
                del private
                self._attempts.pop(owner_id, None)
        except InvalidSecret as exc:
            self._failed(owner_id)
            await message.answer(str(exc))
        except Exception:
            # No traceback/arguments/repr(Update) may contain a secret here.
            await state.clear()
            await message.answer(texts.ACTION_FAILED)
