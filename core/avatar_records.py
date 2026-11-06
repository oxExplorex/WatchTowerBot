"""Portable avatar history metadata; safe to import without the bot or database."""
import re
from uuid import UUID


def validate_avatar_history(record):
    UUID(record["uuid"])
    if (any(type(record.get(key)) is not int or not 0 < record[key] < 2**63
            for key in ("account_user_id", "user_id"))
            or type(record.get("first_seen_at")) is not int or not 0 <= record["first_seen_at"] < 2**63
            or (record.get("ended_at") is not None and (type(record["ended_at"]) is not int
                or not record["first_seen_at"] <= record["ended_at"] < 2**63))
            or record.get("status") not in {"stored", "absent", "unavailable"}
            or not isinstance(record.get("photo_key"), str) or len(record["photo_key"]) > 256
            or (record.get("blob_key") is not None and not re.fullmatch(r"[0-9a-f]{64}", record["blob_key"]))
            or (record["status"] == "stored") != bool(record.get("blob_key"))):
        raise ValueError("Invalid avatar history record")
    return record
