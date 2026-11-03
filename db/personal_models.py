from sqlalchemy import BigInteger
from sqlmodel import Field, SQLModel


class OwnerArchiveKey(SQLModel, table=True):
    __tablename__ = "owner_archive_key"

    owner_id: int = Field(primary_key=True, sa_type=BigInteger)
    public_key: str
    encrypted_private_key: str
    salt: str
    format_version: int = 1
    created_at: int = Field(sa_type=BigInteger)
    migration_state: str = "pending"
    migrated_revisions: int = 0
    migrated_files: int = 0
    last_error: str | None = None
