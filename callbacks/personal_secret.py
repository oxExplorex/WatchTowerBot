"""Keep personal-secret buttons compatible with messages sent before upgrades."""

from enum import Enum

from aiogram.filters.callback_data import CallbackData


class SecretAction(str, Enum):
    SETUP = "setup"
    VERIFY = "verify"


class PersonalSecretCallback(CallbackData, prefix="personal_secret"):
    action: SecretAction


SETUP_CALLBACK = PersonalSecretCallback(action=SecretAction.SETUP).pack()
VERIFY_CALLBACK = PersonalSecretCallback(action=SecretAction.VERIFY).pack()
