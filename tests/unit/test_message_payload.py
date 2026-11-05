import json

from aiogram.enums import MessageEntityType as BotEntityType
from aiogram.types import MessageEntity as BotEntity
from pyrogram.enums import ChatType, MessageEntityType
from pyrogram.types import MessageEntity

from utils.message_payload import enum_value, entities


def test_every_kurigram_entity_type_has_a_json_string_label():
    for kind in MessageEntityType:
        payload = entities([MessageEntity(type=kind, offset=0, length=4)])
        assert json.loads(json.dumps(payload))[0]["type"] == kind.name.lower()
    assert enum_value(ChatType.PRIVATE) == "private"
    assert enum_value("private") == "private"


def test_shared_entity_types_preserve_labels_offsets_and_metadata_across_sdks():
    for kind in MessageEntityType:
        if kind.name not in BotEntityType.__members__:
            continue
        options = dict(offset=2, length=4)
        if kind.name == "TEXT_LINK":
            options["url"] = "https://example.org"
        elif kind.name == "PRE":
            options["language"] = "python"
        elif kind.name == "CUSTOM_EMOJI":
            options["custom_emoji_id"] = "123456789"
        assert entities([MessageEntity(type=kind, **options)]) == entities([
            BotEntity(type=BotEntityType[kind.name], **options)])
