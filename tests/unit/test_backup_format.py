from io import BytesIO
from types import SimpleNamespace

import pytest

from core.backup_format import BackupReader, BackupWriter, InvalidBackup, JSON_FRAME
from core.backup_parts import PartsReader, PartsWriter, parse_part_name
from core.personal_crypto import create_key_bundle


def test_parts_cross_frame_boundaries_and_tampering_is_detected(tmp_path, monkeypatch):
    import core.backup_parts as parts
    monkeypatch.setattr(parts, "PART_SIZE", 128)
    bundle = SimpleNamespace(**create_key_bundle(123, "СекретБекапа123"))
    writer = PartsWriter(tmp_path, "a" * 32)
    archive = BackupWriter(writer, 123, bundle)
    archive.record({"text": "приватные данные"})
    archive.finish()
    paths = writer.finish()
    assert len(paths) > 1
    assert all(parse_part_name(path.name)[2] == len(paths) for path in paths)
    reader = PartsReader(paths)
    try:
        assert list(BackupReader(reader, 123, "СекретБекапа123"))[0][0] == JSON_FRAME
    finally:
        reader.close()
    data = bytearray(b"".join(path.read_bytes() for path in paths))
    data[-2] ^= 1
    with pytest.raises(InvalidBackup):
        list(BackupReader(BytesIO(data), 123, "СекретБекапа123"))
    with pytest.raises(InvalidBackup):
        parse_part_name("../../secret.wtb")


def test_new_reader_accepts_old_frames_and_compressed_metadata():
    import json
    bundle = SimpleNamespace(**create_key_bundle(123, "СекретБекапа123"))
    stream = BytesIO()
    writer = BackupWriter(stream, 123, bundle)
    writer.write(JSON_FRAME, b'{"legacy":true}')
    record = {"text": "Сохранённая переписка\n" * 1000}
    writer.record(record)
    writer.finish()
    assert len(stream.getvalue()) < len(json.dumps(record).encode()) // 4
    stream.seek(0)
    rows = list(BackupReader(stream, 123, "СекретБекапа123"))
    assert all(kind == JSON_FRAME for kind, _ in rows)
    assert [json.loads(data) for _, data in rows] == [{"legacy": True}, record]


def test_authenticated_compressed_metadata_cannot_exceed_frame_limit():
    import zlib
    from core.backup_format import COMPRESSED_JSON_FRAME, MAX_FRAME
    bundle = SimpleNamespace(**create_key_bundle(123, "СекретБекапа123"))
    stream = BytesIO()
    writer = BackupWriter(stream, 123, bundle)
    writer.write(COMPRESSED_JSON_FRAME, zlib.compress(b"A" * (MAX_FRAME + 1)))
    writer.finish()
    stream.seek(0)
    with pytest.raises(InvalidBackup):
        list(BackupReader(stream, 123, "СекретБекапа123"))
