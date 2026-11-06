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
