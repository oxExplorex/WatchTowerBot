"""Versioned, independently authenticated frames; no env key or plaintext files.

WTB1 + u32(header length) + UTF-8 JSON header, then u32(length) +
AES-GCM frames. Each nonce is a random 4-byte prefix plus a u64 counter.
AAD binds the complete header and frame counter. A final authenticated EOF
frame prevents a truncated prefix from becoming a valid backup.
"""
import base64
import hashlib
import json
import os
import struct

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core.personal_crypto import context, public_key, unlock_private_key, unwrap_key, wrap_key
from core.compression import compress_if_smaller, decompress_limited

MAGIC = b"WTB1"
JSON_FRAME, BLOB_FRAME, END_FRAME = 1, 2, 255
COMPRESSED_JSON_FRAME = 3
MAX_FRAME = 1024 * 1024
MAX_HEADER = 16 * 1024
KDF = {"name": "argon2id", "memory_kib": 65536, "iterations": 3, "parallelism": 1, "length": 32}


class InvalidBackup(ValueError):
    pass


def encode_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _read_exact(stream, size):
    data = bytearray()
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk:
            raise InvalidBackup("Truncated backup")
        data.extend(chunk)
    return bytes(data)


class BackupWriter:
    def __init__(self, stream, owner_id, bundle):
        self.stream, self.counter, self.finished = stream, 0, False
        key = os.urandom(32)
        self.prefix = os.urandom(4)
        self.header = {"version": 1, "owner_id": owner_id, "kdf": KDF,
                       "key": {name: getattr(bundle, name) for name in (
                           "public_key", "salt", "encrypted_private_key")},
                       "wrapped_key": base64.b64encode(wrap_key(bundle.public_key, key,
                           context(owner_id, "backup:v1"))).decode("ascii"),
                       "nonce_prefix": base64.b64encode(self.prefix).decode("ascii")}
        header = encode_json(self.header)
        if len(header) > MAX_HEADER:
            raise InvalidBackup("Oversized backup header")
        stream.write(MAGIC + struct.pack(">I", len(header)) + header)
        self.aad = MAGIC + hashlib.sha256(header).digest()
        self.cipher = AESGCM(key)

    def write(self, kind, content=b""):
        if self.finished or kind not in {JSON_FRAME, BLOB_FRAME, COMPRESSED_JSON_FRAME, END_FRAME} or len(content) + 1 > MAX_FRAME:
            raise InvalidBackup("Invalid backup frame")
        counter = self.counter.to_bytes(8, "big")
        ciphertext = self.cipher.encrypt(self.prefix + counter, bytes([kind]) + content, self.aad + counter)
        self.stream.write(struct.pack(">I", len(ciphertext)) + ciphertext)
        self.counter += 1
        self.finished = kind == END_FRAME

    def record(self, value):
        raw = encode_json(value)
        if len(raw) + 1 > MAX_FRAME:
            raise InvalidBackup("Backup record exceeds frame limit")
        packed = compress_if_smaller(raw)
        self.write(COMPRESSED_JSON_FRAME if packed is not None else JSON_FRAME,
                   packed if packed is not None else raw)

    def finish(self):
        self.write(END_FRAME)


class BackupReader:
    def __init__(self, stream, owner_id, secret):
        self.stream, self.counter = stream, 0
        try:
            if _read_exact(stream, 4) != MAGIC:
                raise InvalidBackup("Unsupported backup format")
            length, = struct.unpack(">I", _read_exact(stream, 4))
            if not 1 <= length <= MAX_HEADER:
                raise InvalidBackup("Invalid header size")
            raw = _read_exact(stream, length)
            header = json.loads(raw)
            if (header["version"] != 1 or type(header["owner_id"]) is not int
                    or header["owner_id"] != owner_id or header["kdf"] != KDF):
                raise InvalidBackup("Incompatible backup or owner")
            public_key(header["key"]["public_key"])
            self.private_key = unlock_private_key(owner_id, header["key"], secret)
            self.bundle = header["key"]
            self.prefix = base64.b64decode(header["nonce_prefix"], validate=True)
            if len(self.prefix) != 4:
                raise InvalidBackup("Invalid nonce prefix")
            key = unwrap_key(self.private_key, base64.b64decode(header["wrapped_key"], validate=True),
                             context(owner_id, "backup:v1"))
            self.cipher = AESGCM(key)
            self.aad = MAGIC + hashlib.sha256(raw).digest()
        except InvalidBackup:
            raise
        except Exception:
            raise InvalidBackup("Invalid backup or secret") from None

    def __iter__(self):
        while True:
            length, = struct.unpack(">I", _read_exact(self.stream, 4))
            if not 17 <= length <= MAX_FRAME + 16:
                raise InvalidBackup("Invalid frame size")
            counter = self.counter.to_bytes(8, "big")
            try:
                plain = self.cipher.decrypt(self.prefix + counter, _read_exact(self.stream, length), self.aad + counter)
            except Exception:
                raise InvalidBackup("Backup authentication failed") from None
            self.counter += 1
            kind, content = plain[0], plain[1:]
            if kind == COMPRESSED_JSON_FRAME:
                try:
                    content = decompress_limited(content, MAX_FRAME - 1)
                except ValueError:
                    raise InvalidBackup("Invalid compressed metadata frame") from None
                kind = JSON_FRAME
            if kind == END_FRAME:
                if content or self.stream.read(1):
                    raise InvalidBackup("Data after backup end")
                return
            if kind not in {JSON_FRAME, BLOB_FRAME}:
                raise InvalidBackup("Unknown frame")
            yield kind, content
