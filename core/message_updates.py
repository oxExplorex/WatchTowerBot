from contextvars import ContextVar

from core.async_tools import tracked_job

_update_identity: ContextVar[tuple[int, str] | None] = ContextVar("message_update_identity", default=None)


@tracked_job
async def remember_update_identity(client, update, users, chats):
    # Raw and parsed handlers run in the same SDK worker task. Replace context for
    # every packet so an identity cannot leak to a later unrelated update.
    sequence = getattr(update, "pts", None) or getattr(update, "qts", None)
    value = f"{type(update).__name__}:{sequence}" if sequence is not None else None
    _update_identity.set((id(client), value) if value is not None else None)


def current_update_identity(client) -> str | None:
    value = _update_identity.get()
    return value[1] if value is not None and value[0] == id(client) else None
