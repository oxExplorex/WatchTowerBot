"""Compose handlers explicitly without loading the application on package import."""
from aiogram import Router


def build_router() -> Router:
    from .accounts_menu_handler import router as accounts_menu_handler_router
    from .accounts_add_handler import router as accounts_add_handler_router
    from .account_edit_handler import router as account_edit_handler_router
    from .account_del_handler import router as account_del_handler_router
    from .chat_history_handler import router as chat_history_handler_router

    router = Router(name=__name__)
    router.include_routers(
        accounts_menu_handler_router,
        accounts_add_handler_router,
        account_edit_handler_router,
        account_del_handler_router,
        chat_history_handler_router,
    )
    return router
