"""Compose handlers explicitly without loading the application on package import."""
from aiogram import Router


def build_router() -> Router:
    from .apps_menu_handler import router as apps_menu_handler_router
    from .apps_add_handler import router as apps_add_handler_router
    from .apps_del_handler import router as apps_del_handler_router

    router = Router(name=__name__)
    router.include_routers(
        apps_menu_handler_router,
        apps_add_handler_router,
        apps_del_handler_router,
    )
    return router
