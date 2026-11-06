"""Archive counts from the DB plus actual encrypted file sizes, without decryption."""
import asyncio

from core.media_store import MediaStore


def stored_bytes(store, owner_id, keys):
    total = missing = 0
    for key in keys:
        try:
            total += store.path(owner_id, key).stat().st_size
        except (OSError, ValueError):
            missing += 1
    return total, missing


async def archive_statistics(repository, owner_id, *, store=None):
    result = await repository.statistics(owner_id)
    keys = await repository.media_references(owner_id)
    size, missing = await asyncio.to_thread(stored_bytes, store or MediaStore.from_environment(), owner_id, keys)
    result.update(media_files=len(keys), media_bytes=size, media_unavailable=missing,
                  archive_bytes=result["content_bytes"] + size)
    return result
