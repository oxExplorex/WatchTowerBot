from aiogram.fsm.state import State, StatesGroup


class AdminStates(StatesGroup):
    apps_add_app_id = State()
    apps_add_api_hash = State()
    apps_add_tag_name = State()
    apps_add_agree = State()

    account_add_number = State()
    account_add_code = State()
    account_add_password = State()

    wait_proxy_manager = State()
    wait_chat_history_search = State()
