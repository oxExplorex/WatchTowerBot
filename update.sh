#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
python3 -m pip install -r requirements.txt
python3 scripts/update_bot.py
python3 -c "import asyncio; from db.migrations import run_db_migrations; asyncio.run(run_db_migrations())"
