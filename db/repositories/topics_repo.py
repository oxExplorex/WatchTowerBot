from sqlalchemy import delete, update

from db.repositories.base import conflict_insert
from db.topic_models import BotPhotoCache, NotificationTopic, TopicReminder


class TopicsRepository:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def get_photo(self, bot_id, image_hash):
        async with self.session_factory()() as session:
            row = await session.get(BotPhotoCache, (bot_id, image_hash))
            return row.file_id if row else None

    async def save_photo(self, bot_id, image_hash, file_id):
        async with self.session_factory()() as session, session.begin():
            insert = conflict_insert(session, BotPhotoCache).values(
                bot_id=bot_id, image_hash=image_hash, file_id=file_id)
            await session.execute(insert.on_conflict_do_update(
                index_elements=["bot_id", "image_hash"], set_={"file_id": file_id}))

    async def discard_photo(self, bot_id, image_hash, file_id):
        async with self.session_factory()() as session, session.begin():
            await session.execute(delete(BotPhotoCache).where(BotPhotoCache.bot_id == bot_id,
                BotPhotoCache.image_hash == image_hash, BotPhotoCache.file_id == file_id))

    async def get(self, bot_id, owner_id, key):
        async with self.session_factory()() as session:
            row = await session.get(NotificationTopic, (bot_id, owner_id, key))
            return row.thread_id if row else None

    async def save(self, bot_id, owner_id, key, thread_id):
        async with self.session_factory()() as session, session.begin():
            insert = conflict_insert(session, NotificationTopic).values(
                bot_id=bot_id, owner_id=owner_id, topic_key=key, thread_id=thread_id)
            await session.execute(insert.on_conflict_do_update(
                index_elements=["bot_id", "owner_id", "topic_key"], set_={"thread_id": thread_id}))

    async def discard(self, bot_id, owner_id, key, thread_id):
        async with self.session_factory()() as session, session.begin():
            await session.execute(delete(NotificationTopic).where(NotificationTopic.bot_id == bot_id,
                NotificationTopic.owner_id == owner_id, NotificationTopic.topic_key == key,
                NotificationTopic.thread_id == thread_id))

    async def claim_reminder(self, bot_id, owner_id, now, first_deadline):
        async with self.session_factory()() as session, session.begin():
            await session.execute(conflict_insert(session, TopicReminder).values(
                bot_id=bot_id, owner_id=owner_id, next_at=first_deadline).on_conflict_do_nothing())
            result = await session.execute(update(TopicReminder).where(TopicReminder.bot_id == bot_id,
                TopicReminder.owner_id == owner_id, TopicReminder.next_at <= now).values(
                next_at=now + 300).returning(TopicReminder.owner_id))
            return result.scalar_one_or_none() is not None

    async def postpone_reminder(self, bot_id, owner_id, deadline):
        async with self.session_factory()() as session, session.begin():
            await session.execute(update(TopicReminder).where(TopicReminder.bot_id == bot_id,
                TopicReminder.owner_id == owner_id).values(next_at=deadline))
