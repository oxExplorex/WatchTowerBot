@echo off
setlocal
cd /d "%~dp0"

python -m pip uninstall -y google-generativeai
python -m pip install -r requirements.txt
python scripts\update_bot.py
python -m alembic upgrade head
