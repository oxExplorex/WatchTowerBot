"""Compose handlers explicitly without loading the application on package import."""
from aiogram import Router


def build_router() -> Router:
    from .business_handler import router as business_handler_router
    from .business_del_handler import router as business_del_handler_router
    from .business_edit_handler import router as business_edit_handler_router

    router = Router(name=__name__)
    router.include_routers(
        business_handler_router,
        business_del_handler_router,
        business_edit_handler_router,
    )
    return router
