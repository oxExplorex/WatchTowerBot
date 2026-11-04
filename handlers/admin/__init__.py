"""Compose handlers explicitly without loading the application on package import."""
from aiogram import Router


def build_router() -> Router:
    from .admin_menu_handler import router as admin_menu_handler_router
    from .admins_handler import router as admins_handler_router
    from .apps_manager import build_router as build_apps_manager_router
    from .panel import build_router as build_panel_router
    from .proxy_manager import router as proxy_manager_router
    from .reboot import router as reboot_router
    from .settings import router as settings_router

    router = Router(name=__name__)
    router.include_routers(
        admin_menu_handler_router,
        admins_handler_router,
        build_apps_manager_router(),
        build_panel_router(),
        proxy_manager_router,
        reboot_router,
        settings_router,
    )
    return router
