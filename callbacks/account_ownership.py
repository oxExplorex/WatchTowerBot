from aiogram.filters.callback_data import CallbackData


class OwnAccount(CallbackData, prefix="own"):
    action: str
    token: str = "-"
    page: int = 0
