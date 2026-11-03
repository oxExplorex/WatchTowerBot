"""Streaming authenticated encryption. Only ciphertext is written to disk."""
import hashlib
import hmac
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import zlib

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from utils.crypto_store import media_encryption_key
from core.personal_crypto import context, unwrap_key, wrap_key

MAGIC = b"WTM1"
PERSONAL_MAGIC = b"WTM2"
HEADER_SIZE = len(MAGIC) + 1 + 12
DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "data" / "media"


class MediaTooLarge(ValueError):
    pass


class MediaQuotaExceeded(OSError):
    pass


class MediaStore:
    def __init__(self, root=DEFAULT_ROOT, *, max_file_bytes=100 * 1024**2, max_total_bytes=5 * 1024**3):
        self.root = Path(root)
        self.max_file_bytes = max_file_bytes
        self.max_total_bytes = max_total_bytes

    def path(self, owner_id, blob_key):
        if not isinstance(owner_id, int) or owner_id <= 0 or not re.fullmatch(r"[0-9a-f]{64}", blob_key):
            raise ValueError("Invalid media identity")
        return self.root / str(owner_id) / blob_key[:2] / f"{blob_key}.wtm"

    def writer(self, owner_id, *, compress=False, public_key=None, replace_legacy=False):
        return EncryptedMediaWriter(self, owner_id, compress=compress, public_key=public_key, replace_legacy=replace_legacy)

    def version(self, owner_id, blob_key):
        with self.path(owner_id, blob_key).open("rb") as stream:
            magic = stream.read(4)
        if magic == MAGIC:
            return 1
        if magic == PERSONAL_MAGIC:
            return 2
        raise ValueError("Unsupported encrypted media format")

    def legacy_blob(self, owner_id):
        # A crash may publish ciphertext before its queue transaction commits.
        # Preserve and encrypt such orphan blobs too, never remove their history.
        owner_root = self.path(owner_id, "0" * 64).parents[1]
        for path in owner_root.glob("*/*.wtm"):
            identity = path.stem
            if re.fullmatch(r"[0-9a-f]{64}", identity) and path == self.path(owner_id, identity):
                if path.is_symlink() or path.parent.is_symlink() or owner_root.is_symlink():
                    raise ValueError("Unsafe media migration path")
                if self.version(owner_id, identity) == 1:
                    return identity
        return None

    def cleanup_parts(self):
        # Never remove another worker's live download (timeout 600s, lease 660s).
        for path in self.root.glob("*.part"):
            if path.stat().st_mtime < time.time() - 3600:
                path.unlink(missing_ok=True)

    def read(self, owner_id, blob_key, *, private_key=None):
        """Internal bounded reader; authenticate before returning any plaintext."""
        path = self.path(owner_id, blob_key)
        if path.stat().st_size > self.max_file_bytes * 2 + 1024:
            raise MediaTooLarge("Encrypted file exceeds read limit")
        content = path.read_bytes()
        header = content[:HEADER_SIZE]
        if len(content) < HEADER_SIZE + 16 or header[:4] not in (MAGIC, PERSONAL_MAGIC) or header[4] not in (0, 1):
            raise ValueError("Unsupported encrypted media format")
        if header[:4] == PERSONAL_MAGIC:
            if private_key is None:
                raise PermissionError("Personal secret is required to read archived media")
            header = content[:HEADER_SIZE + 384]
            key = unwrap_key(private_key, header[HEADER_SIZE:], context(owner_id, "media"))
        else:
            key = media_encryption_key(owner_id)
        data = AESGCM(key).decrypt(header[5:HEADER_SIZE], content[len(header):], header)
        if header[4]:
            decoder = zlib.decompressobj()
            data = decoder.decompress(data, self.max_file_bytes + 1)
            if not decoder.eof or decoder.unused_data:
                raise ValueError("Invalid or oversized compressed media")
        if len(data) > self.max_file_bytes:
            raise MediaTooLarge("Decrypted file exceeds read limit")
        digest = hmac.new(media_encryption_key(owner_id), b"content\0" + data, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(digest, blob_key):
            raise ValueError("Media identity mismatch")
        return data

    def migrate_blob(self, owner_id, blob_key, public_key):
        """Bounded plaintext in memory, atomic ciphertext replacement, crash safe."""
        if self.version(owner_id, blob_key) == 2:
            return
        data = self.read(owner_id, blob_key)
        with self.path(owner_id, blob_key).open("rb") as stream:
            compress = stream.read(5)[4] == 1
        old_size = self.path(owner_id, blob_key).stat().st_size
        with self.writer(owner_id, compress=compress, public_key=public_key, replace_legacy=old_size) as writer:
            for offset in range(0, len(data), 1024 * 1024):
                writer.write(data[offset:offset + 1024 * 1024])
            actual, _ = writer.finish()
            if actual != blob_key:
                raise ValueError("Media identity changed during migration")


class EncryptedMediaWriter:
    def __init__(self, store, owner_id, *, compress, public_key=None, replace_legacy=False):
        identity_key = media_encryption_key(owner_id)  # Fail before creating a file.
        key = os.urandom(32) if public_key else identity_key
        self.replace_legacy = replace_legacy
        store.path(owner_id, "0" * 64)
        self.store, self.owner_id = store, owner_id
        store.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        used = sum(path.stat().st_size for path in store.root.rglob("*") if path.is_file())
        # A replacement consumes temporary disk space, but its old immutable
        # version is no longer counted against the logical archive quota.
        replacement_credit = int(replace_legacy) + (384 if replace_legacy else 0)
        available = max(0, store.max_total_bytes - used) if replace_legacy else store.max_total_bytes - used
        self.budget = min(available + replacement_credit,
                          shutil.disk_usage(store.root).free - 128 * 1024**2)
        if self.budget < HEADER_SIZE + 16:
            raise MediaQuotaExceeded("Media storage quota reached")
        descriptor, name = tempfile.mkstemp(prefix="download_", suffix=".part", dir=store.root)
        self.temp_path = Path(name)
        self.file = os.fdopen(descriptor, "wb")
        self.size, self.written = 0, 0
        self.digest = hmac.new(identity_key, b"content\0", hashlib.sha256)
        self.compressor = zlib.compressobj(level=1) if compress else None
        header = (PERSONAL_MAGIC if public_key else MAGIC) + bytes([int(compress)]) + os.urandom(12)
        if public_key:
            header += wrap_key(public_key, key, context(owner_id, "media"))
        self.encryptor = Cipher(algorithms.AES(key), modes.GCM(header[5:HEADER_SIZE])).encryptor()
        self.encryptor.authenticate_additional_data(header)
        self._write(header)

    def _write(self, data):
        if self.written + len(data) > self.budget:
            raise MediaQuotaExceeded("Media storage quota reached")
        self.file.write(data)
        self.written += len(data)

    def write(self, data):
        if self.size + len(data) > self.store.max_file_bytes:
            raise MediaTooLarge("Media file exceeds archive limit")
        self.size += len(data)
        self.digest.update(data)
        self._write(self.encryptor.update(self.compressor.compress(data) if self.compressor else data))
        return len(data)

    def flush(self):
        self.file.flush()

    def finish(self):
        if self.compressor:
            self._write(self.encryptor.update(self.compressor.flush()))
        self._write(self.encryptor.finalize() + self.encryptor.tag)
        self.file.flush()
        os.fsync(self.file.fileno())
        self.file.close()
        blob_key = self.digest.hexdigest()
        target = self.store.path(self.owner_id, blob_key)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Hard-link publication never overwrites an existing immutable blob. This
        # also arbitrates concurrent workers and crash retries with equal bytes.
        if self.replace_legacy:
            os.replace(self.temp_path, target)
        else:
            try:
                os.link(self.temp_path, target)
            except FileExistsError:
                pass
            self.temp_path.unlink()
        return blob_key, self.size

    def close(self):
        self.file.close()
        self.temp_path.unlink(missing_ok=True)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
