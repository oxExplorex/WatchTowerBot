@echo off
setlocal
cd /d "%~dp0"

python -m pip uninstall -y google-generativeai
python scripts\update_bot.py
if errorlevel 1 exit /b %errorlevel%
python scripts\install_dependencies.py
if errorlevel 1 exit /b %errorlevel%
python -c "import asyncio; from db.migrations import run_db_migrations; asyncio.run(run_db_migrations())"
