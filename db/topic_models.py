"""Private-chat topic routing and durable reminder deadlines."""
from sqlalchemy import BigInteger
from sqlmodel import Field, SQLModel


class NotificationTopic(SQLModel, table=True):
    __tablename__ = "notification_topic"
    bot_id: int = Field(primary_key=True, sa_type=BigInteger)
    owner_id: int = Field(primary_key=True, sa_type=BigInteger)
    topic_key: str = Field(primary_key=True)
    thread_id: int = Field(sa_type=BigInteger)


class TopicReminder(SQLModel, table=True):
    __tablename__ = "topic_reminder"
    bot_id: int = Field(primary_key=True, sa_type=BigInteger)
    owner_id: int = Field(primary_key=True, sa_type=BigInteger)
    next_at: int = Field(sa_type=BigInteger)


class BotPhotoCache(SQLModel, table=True):
    __tablename__ = "bot_photo_cache"
    bot_id: int = Field(primary_key=True, sa_type=BigInteger)
    image_hash: str = Field(primary_key=True)
    file_id: str
