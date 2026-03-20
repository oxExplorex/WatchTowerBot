from __future__ import annotations

import base64
import hashlib
import hmac
import os

from cryptography.fernet import Fernet, InvalidToken

_ENC_PREFIX = "enc:v1:"


def _raw_key() -> str:
    return (os.getenv("DB_ENCRYPTION_KEY") or "").strip()


def encryption_enabled() -> bool:
    return bool(_raw_key())


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


def is_encrypted(value: str | None) -> bool:
    return bool(value and str(value).startswith(_ENC_PREFIX))


def encrypt_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value)
    if not text:
        return ""
    if is_encrypted(text):
        return text
    fernet = _derive_fernet()
    if fernet is None:
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
        return text
    token = text[len(_ENC_PREFIX) :]
    try:
        return fernet.decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return text
