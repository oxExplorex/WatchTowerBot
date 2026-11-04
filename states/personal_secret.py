"""State names are persisted contracts; preserve the PersonalSecret group name."""

from aiogram.fsm.state import State, StatesGroup


class PersonalSecret(StatesGroup):
    input = State()
    confirm = State()
    verify = State()
    transfer = State()


SECRET_INPUT = PersonalSecret.input.state
SECRET_CONFIRM = PersonalSecret.confirm.state
SECRET_VERIFY = PersonalSecret.verify.state
SECRET_TRANSFER = PersonalSecret.transfer.state
SECRET_STATES = {SECRET_INPUT, SECRET_CONFIRM, SECRET_VERIFY, SECRET_TRANSFER}
