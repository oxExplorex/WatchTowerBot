from sqlalchemy.engine import make_url


def test_postgres_credentials_roundtrip_through_runtime_and_alembic(offline_module):
    engine = offline_module("db/engine.py")
    migrations = offline_module("db/migrations.py")
    settings = engine.DatabaseSettings(
        engine="postgres", name="test_database", user="test@user",
        password="synthetic@pass:/%#word", host="localhost", port=5432,
        path="unused", admin_name="postgres",
    )
    runtime_url = settings.connection_string
    config = migrations._build_alembic_config(runtime_url)
    assert config.get_main_option("sqlalchemy.url") == runtime_url
    for url in (runtime_url, config.get_main_option("sqlalchemy.url")):
        parsed = make_url(url)
        assert parsed.username == settings.user
        assert parsed.password == settings.password
        assert parsed.database == settings.name
