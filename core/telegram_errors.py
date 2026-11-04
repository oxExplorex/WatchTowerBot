"""Shared classification of unusable Telegram authorizations."""

FATAL_SESSION_ERROR_NAMES = frozenset({
    "AuthKeyDuplicated", "AuthKeyInvalid", "AuthKeyPermEmpty", "AuthKeyUnregistered",
    "SessionExpired", "SessionPasswordNeeded", "SessionRevoked", "Unauthorized",
    "UserDeactivated", "UserDeactivatedBan",
})
_FATAL_MARKERS = (
    "auth key unregistered", "auth key invalid", "session revoked", "session expired",
    "unauthorized", "user deactivated",
)


def is_fatal_session_error(error: Exception, *, include_not_started: bool = False) -> bool:
    if type(error).__name__ in FATAL_SESSION_ERROR_NAMES:
        return True
    text = str(error).lower()
    return any(marker in text for marker in _FATAL_MARKERS) or (
        include_not_started and "client has not been started yet" in text
    )
