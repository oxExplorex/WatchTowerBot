from __future__ import annotations

import base64
import hashlib
import hmac
import os

from cryptography.fernet import Fernet, InvalidToken

_ENC_PREFIX = "enc:v1:"


class DecryptionError(RuntimeError):
    """Encrypted data cannot be read with the configured key."""


def _raw_key() -> str:
    return (os.getenv("DB_ENCRYPTION_KEY") or "").strip()


def encryption_enabled() -> bool:
    return bool(_raw_key())


def encrypt_service_secret(value: str | None) -> str | None:
    if not encryption_enabled():
        raise RuntimeError("DB_ENCRYPTION_KEY is required for service secrets")
    return encrypt_text(value)


def service_secret_index(value: str | None, *, purpose: str) -> str | None:
    if value is None:
        return None
    key = _derive_index_key()
    if not key:
        raise RuntimeError("DB_ENCRYPTION_KEY is required for service secrets")
    # Preserve exact comparison, unlike case-insensitive username lookup.
    payload = purpose.encode("utf-8") + b"\0" + value.encode("utf-8")
    return hmac.new(key, b"service-secret\0" + payload, hashlib.sha256).hexdigest()


def _derive_fernet() -> Fernet | None:
    raw = _raw_key()
    if not raw:
        return None
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def _derive_index_key() -> bytes:
    raw = _raw_key()
    if not raw:
        return b""
    return hashlib.sha256(("idx:" + raw).encode("utf-8")).digest()


def blind_index(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if not normalized:
        return None
    idx_key = _derive_index_key()
    if not idx_key:
        return None
    return hmac.new(idx_key, normalized.encode("utf-8"), hashlib.sha256).hexdigest()


def message_fingerprint(value: str) -> str:
    key = _derive_index_key()
    if not key:
        raise RuntimeError("DB_ENCRYPTION_KEY is required for message storage")
    # Unlike username lookup, message identity is case sensitive and domain separated.
    return hmac.new(key, b"message\0" + value.encode("utf-8"), hashlib.sha256).hexdigest()


def media_encryption_key(owner_id: int) -> bytes:
    raw = _raw_key()
    if not raw:
        raise RuntimeError("DB_ENCRYPTION_KEY is required for media storage")
    return hmac.new(raw.encode("utf-8"), f"media:v1:owner:{owner_id}".encode(), hashlib.sha256).digest()


def is_encrypted(value: str | None) -> bool:
    return bool(value and str(value).startswith(_ENC_PREFIX))


def encrypt_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value)
    if not text:
        return ""
    fernet = _derive_fernet()
    if fernet is None:
        return text
    if is_encrypted(text):
        try:
            fernet.decrypt(text[len(_ENC_PREFIX):].encode("utf-8"))
        except (InvalidToken, ValueError):
            # Incoming names may literally start with the storage prefix. Do not
            # store these as malformed ciphertext and break the next startup.
            pass
        else:
            return text
    token = fernet.encrypt(text.encode("utf-8")).decode("utf-8")
    return f"{_ENC_PREFIX}{token}"


def decrypt_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value)
    if not text:
        return ""
    if not is_encrypted(text):
        return text
    fernet = _derive_fernet()
    if fernet is None:
        raise DecryptionError("Cannot decrypt stored data: encryption key is missing")
    token = text[len(_ENC_PREFIX) :]
    try:
        return fernet.decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        raise DecryptionError("Cannot decrypt stored data: key is incorrect or data is damaged") from None
