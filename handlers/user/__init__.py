"""Compose handlers explicitly without loading the application on package import."""
from aiogram import Router


def build_router() -> Router:
    from .business import build_router as build_business_router
    from .any_message_handler import router as any_message_handler_router

    router = Router(name=__name__)
    router.include_routers(
        build_business_router(),
        any_message_handler_router,
    )
    return router
