#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
python3 -m pip install -r requirements.txt
python3 scripts/update_bot.py
python3 -m alembic upgrade head
