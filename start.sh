#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

if [ -d ".venv" ]; then
    echo "Activating virtual environment (.venv)..."
    source .venv/bin/activate
elif [ -d "venv" ]; then
    echo "Activating virtual environment (venv)..."
    source venv/bin/activate
else
    echo "Warning: No virtual environment (.venv or venv) found. Running with system python."
fi

if [ -f ".env" ]; then
    echo "Loading environment variables from .env..."
    export $(grep -v '^#' .env | xargs)
fi

echo "Starting Telegram Bot via Uvicorn..."
exec uvicorn bot.main:app --host "${WEB_HOST:-${HOST:-0.0.0.0}}" --port "${WEB_PORT:-${PORT:-8000}}"
