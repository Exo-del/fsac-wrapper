#!/usr/bin/env bash
# FSAC Wrapper — one-shot launcher
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8000}"

if [ ! -d .venv ]; then
  echo "→ creating virtualenv…"
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip -q
  .venv/bin/pip install -r requirements.txt -q
fi

if [ ! -f .env ] && [ -f .env.example ]; then
  cp .env.example .env
fi

echo "→ starting FSAC Wrapper on http://127.0.0.1:${PORT}"
exec .venv/bin/python runner.py
