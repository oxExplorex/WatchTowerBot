"""Owner archive envelopes. No private keys or passwords are cached here."""
import base64
from functools import lru_cache
import hashlib
import hmac
import os
import unicodedata

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from core.compression import compress_if_smaller, decompress_limited

PREFIX = "enc:v2:"
COMPRESSED_PREFIX = "enc:v2z:"
MAX_TEXT_BYTES = 1024 * 1024
_COMPARISON_KEY = os.urandom(32)


class InvalidSecret(ValueError):
    pass


def normalize_secret(value: str) -> str:
    if len(value) > 256:
        raise InvalidSecret("Секрет слишком длинный: максимум 256 символов.")
    value = unicodedata.normalize("NFC", value).lower().replace(" ", "")
    if not 6 <= len(value) <= 128 or not value.isalnum():
        raise InvalidSecret("Нужно от 6 до 128 букв и цифр. Другие символы запрещены.")
    common = {"password", "password1", "qwerty", "qwerty123", "пароль", "пароль123", "йцукен", "admin123", "abcdef", "абвгде"}
    if value in common or len(set(value)) < 3 or value.isdecimal():
        raise InvalidSecret("Слишком простой секрет. Придумайте менее очевидное сочетание букв и цифр.")
    for width in range(1, len(value) // 2 + 1):
        if len(value) % width == 0 and value == value[:width] * (len(value) // width):
            raise InvalidSecret("Не используйте повторяющуюся последовательность.")
    return value


def context(owner_id: int, purpose: str) -> bytes:
    return f"watchtower:v2:{owner_id}:{purpose}".encode("ascii")


def _password_key(secret: str, salt: bytes) -> bytes:
    return Argon2id(salt=salt, length=32, iterations=3, lanes=1, memory_cost=64 * 1024).derive(
        normalize_secret(secret).encode("utf-8"))


def create_key_bundle(owner_id: int, secret: str) -> dict[str, str]:
    # Validate before generating an expensive key. Run this function off the loop.
    normalize_secret(secret)
    private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    public = private.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    raw = private.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    salt, nonce = os.urandom(16), os.urandom(12)
    encrypted = AESGCM(_password_key(secret, salt)).encrypt(nonce, raw, context(owner_id, "private") + public)
    return {"public_key": base64.b64encode(public).decode(), "salt": base64.b64encode(salt).decode(),
            "encrypted_private_key": base64.b64encode(nonce + encrypted).decode()}


def unlock_private_key(owner_id: int, bundle, secret: str):
    def field(name):
        return bundle[name] if isinstance(bundle, dict) else getattr(bundle, name)
    try:
        public = base64.b64decode(field("public_key"), validate=True)
        salt = base64.b64decode(field("salt"), validate=True)
        encrypted = base64.b64decode(field("encrypted_private_key"), validate=True)
        raw = AESGCM(_password_key(secret, salt)).decrypt(encrypted[:12], encrypted[12:], context(owner_id, "private") + public)
        private = serialization.load_der_private_key(raw, password=None)
        actual = private.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        if not hmac.compare_digest(actual, public):
            raise ValueError()
        return private
    except (InvalidTag, ValueError, TypeError):
        raise InvalidSecret("Секрет не подошёл или ключ повреждён.") from None


@lru_cache(maxsize=256)
def public_key(encoded: str):
    key = serialization.load_der_public_key(base64.b64decode(encoded, validate=True))
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size != 3072:
        raise ValueError("Unsupported archive public key")
    return key


def _oaep(aad):
    return padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=aad)


def wrap_key(public: str, key: bytes, aad: bytes) -> bytes:
    return public_key(public).encrypt(key, _oaep(aad))


def unwrap_key(private, wrapped: bytes, aad: bytes) -> bytes:
    return private.decrypt(wrapped, _oaep(aad))


def seal_text(public: str, value: str, aad: bytes) -> str:
    raw = value.encode("utf-8")
    if len(raw) > MAX_TEXT_BYTES:
        raise ValueError("Archive text exceeds storage limit")
    packed = compress_if_smaller(raw)
    prefix = PREFIX
    if packed is not None:
        raw, prefix, aad = packed, COMPRESSED_PREFIX, aad + b"\0zlib"
    key, nonce = os.urandom(32), os.urandom(12)
    wrapped = wrap_key(public, key, aad)
    encrypted = AESGCM(key).encrypt(nonce, raw, aad)
    return prefix + base64.b64encode(wrapped + nonce + encrypted).decode()


def open_text(private, value: str, aad: bytes) -> str:
    compressed = value.startswith(COMPRESSED_PREFIX)
    prefix = COMPRESSED_PREFIX if compressed else PREFIX
    if not value.startswith(prefix):
        raise ValueError("Not a personal archive envelope")
    content = base64.b64decode(value[len(prefix):], validate=True)
    if compressed:
        aad += b"\0zlib"
    size = private.key_size // 8
    key = unwrap_key(private, content[:size], aad)
    raw = AESGCM(key).decrypt(content[size:size + 12], content[size + 12:], aad)
    if compressed:
        raw = decompress_limited(raw, MAX_TEXT_BYTES)
    return raw.decode("utf-8")


def live_fingerprint(value: str) -> str:
    # Keeping an env-keyed content digest would permit dictionary guesses using a
    # stolen bot folder. This comparison key exists only for this process lifetime.
    return hmac.new(_COMPARISON_KEY, value.encode("utf-8"), hashlib.sha256).hexdigest()
