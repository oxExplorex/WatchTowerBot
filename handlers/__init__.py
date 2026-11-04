"""Compose handlers explicitly without loading the application on package import."""
from aiogram import Router


def build_router() -> Router:
    from .errors import router as errors_router
    from .admin import build_router as build_admin_router
    from .user import build_router as build_user_router
    from .user.account_ownership import router as own_account_router

    router = Router(name=__name__)
    router.include_routers(
        errors_router,
        own_account_router,
        build_admin_router(),
        build_user_router(),
    )
    return router


def __getattr__(name: str):
    # Compatibility for main and older integrations importing handlers.router.
    if name == "router":
        router = build_router()
        globals()["router"] = router
        return router
    raise AttributeError(name)
