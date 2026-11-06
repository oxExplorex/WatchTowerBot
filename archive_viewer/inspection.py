"""Local archive queries. Counts describe saved records, never Telegram presence."""
from collections import Counter
from datetime import datetime, timezone
import json
import re
from html import escape


def messages(archive, key, limit=None):
    rows = archive.chats[key]
    for offset in range(max(0, len(rows) - limit) if limit else 0, len(rows), 50):
        end = min(offset + 50, len(rows))
        yield from archive.page(key, end)["messages"][-(end - offset):]


def search(archive, key, *, query="", start="", end="", media=False, before=None):
    low = datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp() if start else None
    high = datetime.fromisoformat(end).replace(tzinfo=timezone.utc).timestamp() + 86400 if end else None
    keys = [key] if key else list(archive.chats)
    found = []
    for chat_key in keys:
        for message in messages(archive, chat_key):
            if query.casefold() not in message["text"].casefold():
                continue
            date = message.get("time")
            if (low is not None and (date is None or date < low)) or (high is not None and (date is None or date >= high)):
                continue
            if media and not message["media"]:
                continue
            found.append(message | {"chat_key": chat_key})
    found.sort(key=lambda row: (row.get("time") or 0, row["message_id"], row["id"]))
    stop = len(found) if before is None else max(0, min(int(before), len(found)))
    begin = max(0, stop - 50)
    return {"messages": found[begin:stop], "before": begin or None, "total": len(found)}


def inspect_chat(archive, key):
    rows = archive.chats[key]
    participants = Counter(str(row.get("sender_id")) for row in rows if row.get("sender_id"))
    gallery, links, words = [], set(), Counter()
    missing_media = 0
    for message in messages(archive, key, limit=500):
        for media in message["media"]:
            gallery.append(media | {"message_id": message["id"], "time": message["time"]})
            missing_media += int(not media["available"])
        links.update(re.findall(r"https?://[^\s<>]+", message["text"]))
        words.update(word.casefold() for word in re.findall(r"[^\W\d_]{5,}", message["text"], re.UNICODE))
    account = rows[0]["account_user_id"]
    others = []
    peers = set(participants) - {str(account)}
    for other, saved in archive.chats.items():
        if other != key and peers.intersection(str(row.get("sender_id")) for row in saved):
            others.append(other)
    graph = Counter()
    for row in rows:
        sender = row.get("sender_id")
        if sender:
            target = row["chat_id"] if sender == account else account
            graph[(str(sender), str(target))] += 1
    return dict(messages=len(rows), edited=sum(bool(row["is_edited"]) for row in rows),
        deleted=sum(bool(row["is_deleted"]) for row in rows),
        missing=sum(bool(row.get("history_missing_at")) for row in rows),
        revisions=sum(len(archive.revisions.get(row["uuid"], [])) for row in rows),
        original_missing=sum(bool(row["is_edited"]) and not row.get("original_seen", False) for row in rows),
        unknown_date=sum(row.get("sent_at") is None for row in rows), missing_media=missing_media,
        participants=[dict(id=identity, name=archive.names.get(identity, {}).get("full_name") or identity, count=count)
                      for identity, count in participants.most_common()],
        gallery=gallery[-120:], media_total=sum(len(archive.by_revision.get(row.get("latest_revision_uuid"), [])) for row in rows),
        sample_messages=min(500, len(rows)), links=sorted(links)[:30],
        keywords=words.most_common(12), shared=others[:20],
        graph=[dict(source=source, target=target, count=count) for (source, target), count in graph.items()])


def gallery(archive, key, before=None):
    rows = archive.chats[key]
    end = len(rows) if before is None else max(0, min(int(before), len(rows)))
    output = []
    cursor = end
    while cursor > 0 and len(output) < 60:
        cursor -= 1
        row = rows[cursor]
        revisions = archive.revisions.get(row["uuid"], [])
        revision = next((value for value in revisions if value["uuid"] == row.get("latest_revision_uuid")), None)
        if revision and archive.by_revision.get(revision["uuid"]):
            output.extend(media | {"message_id": row["uuid"], "time": row.get("sent_at")}
                          for media in archive._version(revision)["media"])
    return {"items": output, "before": cursor or None}


def export_chat(archive, key, html=False):
    chats = [chat for chat in archive.chat_list() if not key or chat["key"] == key]
    if key and not chats:
        raise KeyError(key)
    data = [dict(chat=chat, messages=[message | {"history": archive.versions(message["id"])}
                for message in messages(archive, chat["key"])]) for chat in chats]
    if not html:
        return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    body = ['<!doctype html><html lang="ru"><meta charset="utf-8"><title>WatchTower export</title>',
            '<style>body{max-width:900px;margin:40px auto;font:16px system-ui;background:#101923;color:#e5eef6}article{padding:18px;margin:12px 0;background:#203247;border-radius:10px}pre{white-space:pre-wrap;overflow-wrap:anywhere}small{color:#a9bccd}</style>',
            '<p>Расшифрованный экспорт. Вложения находятся в исходном бекапе.</p>']
    for entry in data:
        body.append(f'<h1>{escape(entry["chat"]["name"])}</h1>')
        for message in entry["messages"]:
            label = " · удалено" if message["deleted"] else ""
            date = datetime.fromtimestamp(message["time"], timezone.utc).isoformat() if message.get("time") else "Дата неизвестна"
            body.append(f'<article><small>{escape(str(message["sender"]))} · {date}{label}</small><pre>{escape(message["text"])}</pre>')
            for version in message["history"]:
                body.append(f'<details><summary>Версия · {version.get("time")}</summary><pre>{escape(version["text"])}</pre></details>')
            body.append('</article>')
    return ''.join(body).encode("utf-8")
