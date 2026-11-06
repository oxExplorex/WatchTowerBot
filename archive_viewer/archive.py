"""Read WTB/ZIP backups using only their personal key; plaintext remains in RAM."""
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import zipfile
import re
import zlib

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core.backup_format import BackupReader, BLOB_FRAME, JSON_FRAME, MAGIC, MAX_HEADER, InvalidBackup
from core.backup_parts import MAX_PARTS, PART_SIZE, parse_part_name
from core.personal_crypto import context, open_text, unwrap_key
from archive_viewer.media_types import preview_kind

MAX_METADATA = 256 * 1024 * 1024
MAX_MEDIA = 128 * 1024 * 1024


class _Chain:
    def __init__(self, streams):
        self.streams, self.index = streams, 0

    def read(self, size):
        result = bytearray()
        while len(result) < size and self.index < len(self.streams):
            chunk = self.streams[self.index].read(size - len(result))
            if chunk:
                result.extend(chunk)
            else:
                self.index += 1
        return bytes(result)


def _sources(path, stack):
    path = Path(path)
    if path.suffix.lower() == ".zip":
        archive = stack.enter_context(zipfile.ZipFile(path))
        infos = archive.infolist()
        if not 1 <= len(infos) <= MAX_PARTS:
            raise InvalidBackup("Неверное количество частей ZIP.")
        entries = []
        for info in infos:
            if info.file_size > PART_SIZE or info.is_dir():
                raise InvalidBackup("Неверный размер части ZIP.")
            identity, index, total = parse_part_name(info.filename)
            entries.append((identity, index, total, info))
        entries.sort(key=lambda item: item[1])
        identity, _, total, _ = entries[0]
        if len(entries) != total or any((item[0], item[1], item[2]) != (identity, i, total)
                                       for i, item in enumerate(entries, 1)):
            raise InvalidBackup("В ZIP не хватает частей или смешаны разные бекапы.")
        return _Chain([stack.enter_context(archive.open(item[3])) for item in entries])
    identity, _, total = parse_part_name(path.name)
    paths = [path.parent / f"watchtower-{identity}-{i:04d}-of-{total:04d}.wtb" for i in range(1, total + 1)]
    if any(not item.is_file() or item.stat().st_size > PART_SIZE for item in paths):
        raise InvalidBackup("Положите все части .wtb в одну папку.")
    return _Chain([stack.enter_context(item.open("rb")) for item in paths])


def _owner(path):
    with ExitStack() as stack:
        stream = _sources(path, stack)
        if stream.read(4) != MAGIC:
            raise InvalidBackup("Неизвестный формат бекапа.")
        raw = stream.read(4)
        if len(raw) != 4:
            raise InvalidBackup("Бекап обрезан.")
        size, = struct.unpack(">I", raw)
        if not 1 <= size <= MAX_HEADER:
            raise InvalidBackup("Повреждён заголовок бекапа.")
        owner = json.loads(stream.read(size))["owner_id"]
        if type(owner) is not int or owner <= 0:
            raise InvalidBackup("Неверный владелец архива.")
        return owner


class Archive:
    def __init__(self):
        self.temporary = TemporaryDirectory(prefix="watchtower-viewer-")
        self.messages, self.revisions, self.attachments, self.names, self.blobs = {}, {}, {}, {}, {}
        self._cache = None
        self.by_revision = {}
        self.avatars = {}

    @classmethod
    def open(cls, path, secret):
        archive = cls()
        try:
            archive._load(path, secret)
            return archive
        except Exception:
            archive.close()
            raise InvalidBackup("Не удалось открыть архив. Проверьте секрет, целостность и наличие всех частей.") from None

    def close(self):
        self.messages.clear()
        self.revisions.clear()
        self.attachments.clear()
        self.names.clear()
        self.by_revision.clear()
        self.blobs.clear()
        self.avatars.clear()
        self.chats = {}
        self._cache = None
        self.private_key = None
        self.temporary.cleanup()

    def _load(self, path, secret):
        self.owner = _owner(path)
        metadata, active, remaining, digest, summary, info = 0, None, 0, None, False, False
        with ExitStack() as stack:
            reader = BackupReader(_sources(path, stack), self.owner, secret)
            self.private_key = reader.private_key
            for kind, content in reader:
                if summary:
                    raise InvalidBackup("Data after summary")
                if kind == BLOB_FRAME:
                    if active is None or not content or len(content) > remaining:
                        raise InvalidBackup("Invalid media frame")
                    active.write(content)  # Still authenticated WTM2 ciphertext, never decrypted bytes.
                    remaining -= len(content)
                    digest.update(content)
                    continue
                if kind != JSON_FRAME:
                    raise InvalidBackup("Unknown frame")
                metadata += len(content)
                if metadata > MAX_METADATA:
                    raise InvalidBackup("Metadata limit exceeded")
                item = json.loads(content)
                tag = item["type"]
                if active is not None:
                    if tag != "blob_end" or remaining or digest.hexdigest() != item.get("sha256"):
                        raise InvalidBackup("Incomplete media")
                    active.close()
                    active = None
                    continue
                if not info:
                    if tag != "info" or item.get("scope") != "private":
                        raise InvalidBackup("Unknown archive scope")
                    info = True
                elif tag == "blob":
                    key, size = item["key"], item["size"]
                    if not re.fullmatch(r"[0-9a-f]{64}", key) or key in self.blobs or not 0 < size <= MAX_MEDIA * 2 + 1024:
                        raise InvalidBackup("Invalid media")
                    target = Path(self.temporary.name) / f"{key}.wtm"
                    active = stack.enter_context(target.open("xb"))
                    self.blobs[key] = target
                    remaining, digest = size, hashlib.sha256()
                elif tag == "row":
                    row, table = item["data"], item["table"]
                    if table == "messages":
                        if row["owner_id"] != self.owner or row["chat_id"] <= 0 or row["uuid"] in self.messages:
                            raise InvalidBackup("Foreign or duplicate message")
                        self.messages[row["uuid"]] = row
                    elif table == "revisions":
                        if row["encryption_version"] != 2:
                            raise InvalidBackup("Legacy content is not portable")
                        self.revisions.setdefault(row["message_uuid"], []).append(row)
                    elif table == "attachments":
                        if row["owner_id"] != self.owner or row["uuid"] in self.attachments:
                            raise InvalidBackup("Foreign or duplicate attachment")
                        self.attachments[row["uuid"]] = row
                elif tag == "name":
                    self.names[str(item["user_id"])] = item
                elif tag == "avatar":
                    if (type(item.get("account_user_id")) is not int or item["account_user_id"] <= 0
                            or type(item.get("user_id")) is not int or item["user_id"] <= 0
                            or not re.fullmatch(r"[0-9a-f]{64}", item.get("blob_key", ""))):
                        raise InvalidBackup("Invalid avatar")
                    self.avatars[f'{item["account_user_id"]}:{item["user_id"]}'] = item["blob_key"]
                elif tag == "summary":
                    summary = True
                elif tag != "coverage":
                    raise InvalidBackup("Unknown record")
            if not summary or active is not None:
                raise InvalidBackup("Incomplete archive")
        for identity, revisions in self.revisions.items():
            if identity not in self.messages:
                raise InvalidBackup("Unknown message")
            revisions.sort(key=lambda row: (row["version_at"], row["revision_no"]))
        for item in self.attachments.values():
            self.by_revision.setdefault(item["revision_uuid"], []).append(item)
        self.chats = {}
        for row in self.messages.values():
            key = f'{row["account_user_id"]}:{row["chat_id"]}'
            self.chats.setdefault(key, []).append(row)
        for rows in self.chats.values():
            rows.sort(key=lambda row: (row.get("sent_at") or 0, row["message_id"]))

    def chat_list(self):
        return [{"key": key, "id": str(rows[0]["chat_id"]), "account": str(rows[0]["account_user_id"]),
                 "name": self.names.get(str(rows[0]["chat_id"]), {}).get("full_name") or str(rows[0]["chat_id"]),
                 "count": len(rows), "last_message_at": max((row.get("sent_at") or 0 for row in rows), default=0),
                 "avatar": key if self.avatars.get(key) in self.blobs else None}
                for key, rows in sorted(self.chats.items(), key=lambda pair:
                    (-max((row.get("sent_at") or 0 for row in pair[1]), default=0), pair[0]))]

    def _version(self, revision):
        payload = json.loads(open_text(self.private_key, revision["payload"],
                                     context(self.owner, f'revision:{revision["uuid"]}')))
        media = []
        for item in self.by_revision.get(revision["uuid"], []):
            entries = payload.get("media") or []
            position = item["position"]
            description = entries[position] if 0 <= position < len(entries) else {}
            media.append({"id": item["uuid"], "kind": description.get("kind", "document"),
                          "preview": preview_kind(description.get("kind", "document"),
                              description.get("mime_type"), description.get("file_name")),
                          "name": description.get("file_name") or "Вложение",
                          "available": item["status"] == "stored" and item.get("blob_key") in self.blobs})
        return {"text": payload.get("text") or payload.get("caption") or "", "media": media,
                "time": revision.get("version_at"), "kind": revision.get("kind"),
                "observed_at": (revision.get("observed_at") or 0) / 1_000_000,
                "revision_no": revision.get("revision_no")}

    def calendar(self, key, offset=0):
        """List only saved days and their first row, without decrypting message bodies."""
        offset = int(offset)
        if not -840 <= offset <= 840:
            raise ValueError("Invalid timezone offset")
        zone = timezone(timedelta(minutes=offset))
        days = {}
        for index, row in enumerate(self.chats[key]):
            if not row.get("sent_at"):
                continue
            day = datetime.fromtimestamp(row["sent_at"], zone).date().isoformat()
            entry = days.setdefault(day, {"day": day, "start": index, "count": 0})
            entry["count"] += 1
        return {"days": list(days.values()), "offset": offset}

    def page(self, key, before=None, start=None):
        rows = self.chats[key]
        if start is None:
            end = len(rows) if before is None else max(0, min(before, len(rows)))
            start = max(0, end - 50)
        else:
            if before is not None:
                raise ValueError("Conflicting page cursors")
            start = max(0, min(int(start), len(rows)))
            end = min(start + 50, len(rows))
        output = []
        for row in rows[start:end]:
            revisions = self.revisions.get(row["uuid"], [])
            latest = next((r for r in revisions if r["uuid"] == row.get("latest_revision_uuid")), revisions[-1] if revisions else None)
            item = self._version(latest) if latest else {"text": "Содержимое не было сохранено", "media": []}
            sender = str(row.get("sender_id") or "")
            item.update(id=row["uuid"], message_id=row["message_id"], time=row.get("sent_at"),
                sender=self.names.get(sender, {}).get("full_name") or sender,
                outgoing=sender == str(row["account_user_id"]), edited=row["is_edited"], deleted=row["is_deleted"],
                missing=bool(row.get("history_missing_at")), versions=len(revisions),
                edited_at=(row.get("latest_version_at") or (latest or {}).get("version_at")) if row["is_edited"] else None,
                original_seen=bool(row.get("original_seen")),
                avatar=f'{row["account_user_id"]}:{sender}' if self.avatars.get(f'{row["account_user_id"]}:{sender}') in self.blobs else None)
            output.append(item)
        return {"messages": output, "before": start or None, "after": end if end < len(rows) else None}

    def versions(self, identity):
        if identity not in self.messages:
            raise KeyError(identity)
        message = self.messages[identity]
        return [self._version(row) | {"sent_at": message.get("sent_at"),
                "original_seen": bool(message.get("original_seen")), "edited": message["is_edited"]}
                for row in self.revisions.get(identity, [])]

    def media(self, identity):
        item = self.attachments[identity]
        key = item.get("blob_key")
        if item["status"] != "stored" or key not in self.blobs:
            raise KeyError(identity)
        return self._read_blob(key)

    def avatar(self, identity):
        return self._read_blob(self.avatars[identity])

    def _read_blob(self, key):
        if self._cache is not None and self._cache[0] == key:
            return self._cache[1]
        raw = self.blobs[key].read_bytes()
        header = raw[:401]  # WTM2 + compression byte + nonce12 + RSA3072 envelope384.
        if len(raw) < 417 or header[:4] != b"WTM2" or header[4] not in (0, 1):
            raise InvalidBackup("Invalid media")
        symmetric = unwrap_key(self.private_key, header[17:], context(self.owner, "media"))
        data = AESGCM(symmetric).decrypt(header[5:17], raw[401:], header)
        if header[4]:
            decoder = zlib.decompressobj()
            data = decoder.decompress(data, MAX_MEDIA + 1)
            if not decoder.eof or decoder.unused_data:
                raise InvalidBackup("Invalid compressed media")
        if len(data) > MAX_MEDIA:
            raise InvalidBackup("Media limit exceeded")
        self._cache = key, data
        return data
