from db.main import connect_database


async def run_db_migrations() -> None:
    # SQLModel schema bootstrap.
    # connect_database() creates missing tables and applies small compatibility ALTERs.
    await connect_database()
