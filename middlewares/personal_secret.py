"""Private-chat onboarding before ordinary handlers can inspect secret messages."""
import asyncio
from collections import OrderedDict
import time

from aiogram import BaseMiddleware
from aiogram.types import ForceReply, InaccessibleMessage, InlineKeyboardButton, InlineKeyboardMarkup

from core.personal_crypto import InvalidSecret, create_key_bundle, normalize_secret, unlock_private_key
from db.repositories.personal_repo import PersonalKeyRepository
from db.session import get_session_factory

SETUP_CALLBACK = "personal_secret:setup"
VERIFY_CALLBACK = "personal_secret:verify"
SECRET_INPUT = "PersonalSecret:input"
SECRET_CONFIRM = "PersonalSecret:confirm"
SECRET_VERIFY = "PersonalSecret:verify"
SECRET_STATES = {SECRET_INPUT, SECRET_CONFIRM, SECRET_VERIFY}
INPUT_PROMPT = "Введите личный секрет. Сообщение будет удалено после прочтения. /cancel — отмена."
CONFIRM_PROMPT = "Введите секрет ещё раз для подтверждения. Это сообщение тоже будет удалено."
PROMPT = ("Для продолжения установите личный секрет: от 6 букв и цифр, без простых последовательностей. "
          "Можно использовать только буквы, но лучше выбрать длинную фразу из нескольких слов. "
          "Регистр не учитывается, обычные пробелы удаляются. "
          "Секрет защищает сохранённые сообщения и вложения; без него восстановить архив нельзя. "
          "Мониторинг продолжает работать, пока секрет не установлен.")


def setup_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Ввести секрет", callback_data=SETUP_CALLBACK)]])


async def prompt_setup(bot, owner_id):
    await bot.send_message(owner_id, PROMPT, reply_markup=setup_keyboard())


async def notify_missing_secrets(bot):
    from core.logging import bot_logger
    from db.main import get_admin_ids

    repository = PersonalKeyRepository(get_session_factory)
    for owner_id in await get_admin_ids():
        if await repository.get(owner_id) is None:
            try:
                await prompt_setup(bot, owner_id)
            except Exception as exc:
                bot_logger.warning("Secret setup notification unavailable: owner=%s error=%s", owner_id, type(exc).__name__)


class PersonalSecretMiddleware(BaseMiddleware):
    def __init__(self, repository=None, authorize=None):
        self.repository = repository or PersonalKeyRepository(get_session_factory)
        self.authorize = authorize
        self._crypto_limit = asyncio.Semaphore(1)
        self._attempts = OrderedDict()

    async def _crypto(self, function, *args):
        async with self._crypto_limit:
            task = asyncio.create_task(asyncio.to_thread(function, *args))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                await asyncio.gather(task, return_exceptions=True)
                raise

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
    async def _delete(message):
        try:
            await message.delete()
            return True
        except Exception:
            # Never forward an undeleted secret to ordinary handlers or error logs.
            await message.answer("Не удалось удалить сообщение. Удалите его вручную и повторите ввод. Секрет не принят.")
            return False

    async def _begin(self, message, state, *, verify=False):
        from utils.others import close_state_pyrogram_client

        await close_state_pyrogram_client(state)
        await state.clear()
        await state.update_data(secret_expires=int(time.time()) + 600)
        await state.set_state(SECRET_VERIFY if verify else SECRET_INPUT)
        await message.answer(INPUT_PROMPT, protect_content=True, reply_markup=ForceReply(selective=True))

    async def _input(self, message, state, owner_id, key, current):
        if not await self._delete(message):
            return
        if message.text == "/cancel":
            await state.clear()
            await message.answer("Ввод секрета отменён.")
            return
        data = await state.get_data()
        if data.get("secret_expires", 0) < int(time.time()):
            await state.clear()
            await message.answer("Время ввода истекло. Начните заново.", reply_markup=setup_keyboard() if key is None else None)
            return
        if self._blocked(owner_id):
            await message.answer("Слишком много попыток. Повторите через 5 минут.")
            return
        try:
            secret = normalize_secret(message.text or "")
            if current == SECRET_INPUT:
                if key is not None:
                    await state.clear()
                    await message.answer("Секрет уже установлен. Его замена сейчас не поддерживается.")
                    return
                bundle = await self._crypto(create_key_bundle, owner_id, secret)
                # Persistent FSM contains only a password-encrypted key bundle.
                await state.update_data(secret_bundle=bundle)
                await state.set_state(SECRET_CONFIRM)
                await message.answer(CONFIRM_PROMPT, protect_content=True, reply_markup=ForceReply(selective=True))
            else:
                bundle = data.get("secret_bundle") if current == SECRET_CONFIRM else key
                if bundle is None:
                    await state.clear()
                    await message.answer("Начните настройку заново.", reply_markup=setup_keyboard())
                    return
                private = await self._crypto(unlock_private_key, owner_id, bundle, secret)
                del private
                if self.authorize is None:
                    from db.main import is_admin
                    permitted = await is_admin(owner_id)
                else:
                    permitted = await self.authorize(owner_id)
                if not permitted:
                    await state.clear()
                    return
                if current == SECRET_CONFIRM:
                    if not await self.repository.install(owner_id, bundle):
                        await state.clear()
                        await message.answer("Секрет уже был установлен. Повторная настройка отменена.")
                        return
                    await state.clear()
                    await message.answer("Секрет установлен. Новые сообщения защищаются личным ключом, "
                                         "старый архив переносится в фоне и продолжит перенос после перезапуска. "
                                         "Для открытия меню отправьте /start.")
                else:
                    await state.clear()
                    await state.update_data(personal_verified_until=int(time.time()) + 600)
                    await message.answer("Секрет подтверждён на 10 минут для добавления профиля или аккаунта. Повторите нужное действие.")
                self._attempts.pop(owner_id, None)
        except InvalidSecret as exc:
            self._failed(owner_id)
            await message.answer(str(exc))
        except Exception:
            # No traceback/arguments/repr(Update) may contain a secret here.
            await state.clear()
            await message.answer("Не удалось завершить действие с ключом. Откройте /start и попробуйте ещё раз. Секрет не записывается.")

    async def __call__(self, handler, update, data):
        if update.business_message or update.edited_business_message or update.deleted_business_messages:
            return await handler(update, data)
        call = update.callback_query
        if call and isinstance(call.message, InaccessibleMessage):
            await call.answer("Сообщение меню недоступно. Откройте /start.")
            return None
        message = update.message or update.edited_message or (call.message if call else None)
        user = data.get("event_from_user")
        state = data.get("state")
        if message is None or user is None or state is None:
            return None
        if message.chat.type != "private" or message.chat.id != user.id:
            return None
        owner_id = user.id
        key = await self.repository.get(owner_id)
        current = await state.get_state()
        reply = getattr(message, "reply_to_message", None)
        if update.message and current not in SECRET_STATES and reply is not None:
            author = getattr(reply, "from_user", None)
            if (getattr(author, "id", None) == getattr(data["bot"], "id", None)
                    and getattr(reply, "text", None) in {INPUT_PROMPT, CONFIRM_PROMPT}):
                await self._delete(message)
                await message.answer("Диалог ввода был прерван. Начните заново: /secret.")
                return None
        if update.edited_message is not None and current in SECRET_STATES:
            await self._delete(message)
            return None
        if update.message is not None and current in SECRET_STATES:
            await self._input(message, state, owner_id, key, current)
            return None
        callback = call.data if call else ""
        command = (message.text or "").split("@", 1)[0] if update.message else ""
        if callback in {SETUP_CALLBACK, VERIFY_CALLBACK} or command == "/secret":
            if call:
                await call.answer()
            await self._begin(message, state, verify=key is not None)
            return None
        if key is None:
            if call:
                await call.answer("Сначала установите личный секрет.")
            elif update.message and not (message.text or "").startswith("/"):
                await self._delete(message)
            await prompt_setup(data["bot"], owner_id)
            return None
        # A short-lived confirmation contains no decryption key and grants no
        # access to another owner's objects. Deletion does not require this step.
        addition = callback == "apps_admin_menu_add" or callback.startswith("account_admin_menu_add:")
        previous = await state.get_data()
        until = previous.get("personal_verified_until", 0)
        wizard_state = bool(current and (current.startswith("AdminStates:apps_add_") or current.startswith("AdminStates:account_add_")))
        adding = wizard_state and (callback == "agree" or (update.message is not None and not (message.text or "").startswith("/")))
        if (addition or adding) and until < int(time.time()):
            if call:
                await call.answer("Для добавления подтвердите личный секрет.")
            await self._begin(message, state, verify=True)
            return None
        try:
            return await handler(update, data)
        finally:
            # Entry handlers clear FSM data before starting the add wizard.
            next_state = await state.get_state()
            if addition and next_state:
                await state.update_data(personal_verified_until=until)
