from aiogram.filters.callback_data import CallbackData


class OwnAccount(CallbackData, prefix="own"):
    action: str
    token: str = "-"
    page: int = 0


HOME_CALLBACK = OwnAccount(action="home").pack()
