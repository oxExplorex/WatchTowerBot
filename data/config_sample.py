TOKEN_BOT = ""  # Telegram bot token
GEMINI_KEY = ""  # Gemini API key

# Database connection
# Recommended: create dedicated DB for this bot.
# Example name: gemini_message_manager
user = "postgres"
password = "postgres"
database_name = "gemini_message_manager"
# Existing administrative DB used only to create target DB if needed
database_admin_name = "postgres"

host = "localhost"
port = 5432

# DB driver for SQLModel/SQLAlchemy. Recommended for PostgreSQL: postgresql+asyncpg
db_http = "postgresql+asyncpg"

# Optional for sqlite engine:
# database_path = "data/gemini_message_manager.sqlite3"

# Admin users (Telegram user IDs)
admin_id_list = [
    1,
    2,
]

# Logs path
path_logs = "data/logs/log_{d}.log"
