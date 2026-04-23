@echo off
setlocal
cd /d "%~dp0"

python -m pip uninstall -y google-generativeai
python -m pip install -r requirements.txt
python scripts\update_bot.py
python -c "import asyncio; from db.migrations import run_db_migrations; asyncio.run(run_db_migrations())"
