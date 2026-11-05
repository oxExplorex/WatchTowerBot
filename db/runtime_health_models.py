"""Five-minute runtime observations, separate from legacy dialog scan results."""
from sqlalchemy import BigInteger
from sqlmodel import Field, SQLModel


class RuntimeHealth(SQLModel, table=True):
    __tablename__ = "runtime_health"

    component: str = Field(primary_key=True)
    owner_id: int = Field(primary_key=True, sa_type=BigInteger)
    bucket_at: int = Field(primary_key=True, sa_type=BigInteger, index=True)
    observed_at: int = Field(sa_type=BigInteger)
    status: int  # 0: no enabled accounts; 1: ready; 2: partly ready; 3: unavailable.
    expected: int = 0
    available: int = 0
