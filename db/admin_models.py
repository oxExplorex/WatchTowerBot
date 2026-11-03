from sqlalchemy import BigInteger
from sqlmodel import Field, SQLModel


class AdminGrant(SQLModel, table=True):
    __tablename__ = "admin_grant"

    user_id: int = Field(primary_key=True, sa_type=BigInteger)
    granted_by: int | None = Field(default=None, sa_type=BigInteger)
    created_at: int = Field(sa_type=BigInteger)
