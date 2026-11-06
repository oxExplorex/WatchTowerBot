"""Bounded lossless compression before encryption; no plaintext temporary files."""
import zlib


def compress_if_smaller(data, *, minimum_saving=64):
    packed = zlib.compress(data, level=6)
    return packed if len(packed) + minimum_saving < len(data) else None


def decompress_limited(data, limit):
    decoder = zlib.decompressobj()
    try:
        result = decoder.decompress(data, limit + 1)
    except zlib.error:
        raise ValueError("Invalid compressed content") from None
    if len(result) > limit or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError("Invalid or oversized compressed content")
    return result
