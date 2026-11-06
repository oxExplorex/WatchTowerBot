"""Read authenticated personal media without the source server's HMAC/env key."""
from pathlib import Path
import zlib

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core.backup_format import InvalidBackup
from core.media_store import HEADER_SIZE, PERSONAL_MAGIC
from core.personal_crypto import context, unwrap_key


def restore_blob(path, owner_id, private_key, public_key, store):
    path = Path(path)
    if path.stat().st_size > store.max_file_bytes * 2 + 1024:
        raise InvalidBackup("Oversized media")
    content = path.read_bytes()
    size = HEADER_SIZE + 384
    header = content[:size]
    if len(content) < size + 16 or header[:4] != PERSONAL_MAGIC or header[4] not in (0, 1):
        raise InvalidBackup("Unsupported personal media")
    key = unwrap_key(private_key, header[HEADER_SIZE:], context(owner_id, "media"))
    data = AESGCM(key).decrypt(header[5:HEADER_SIZE], content[size:], header)
    if header[4]:
        decoder = zlib.decompressobj()
        data = decoder.decompress(data, store.max_file_bytes + 1)
        if not decoder.eof or decoder.unused_data:
            raise InvalidBackup("Invalid compressed media")
    if len(data) > store.max_file_bytes:
        raise InvalidBackup("Oversized media")
    with store.writer(owner_id, public_key=public_key, compress=bool(header[4])) as writer:
        for offset in range(0, len(data), 1024 * 1024):
            writer.write(data[offset:offset + 1024 * 1024])
        key, stored_size = writer.finish()
    return key, stored_size
