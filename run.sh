#!/usr/bin/env bash
set -e

PROJECT_ROOT="$(pwd)"
VENV_DIR="$PROJECT_ROOT/venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Virtual environment not found. Creating one..."
    python3 -m venv venv
fi

echo "Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# Ensure dependencies are installed
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt > /dev/null 2>&1
fi

echo "===== STARTING APPLICATION SERVICES ====="

# 1. Start FastAPI Gateway
echo "Starting FastAPI gateway (gateway_app.py)..."
uvicorn gateway_app:app --host 0.0.0.0 --port 8000 &
GATEWAY_PID=$!

# 2. Start Telegram Adapter / Bot Listener
if [ -f "telegram_adapter.py" ]; then
    echo "Starting Telegram adapter (telegram_adapter.py)..."
    python telegram_adapter.py &
    TELEGRAM_PID=$!
fi

echo
echo "All services running:"
echo "- FastAPI Gateway PID: $GATEWAY_PID"
[ -n "$TELEGRAM_PID" ] && echo "- Telegram Adapter PID: $TELEGRAM_PID"
echo "Press Ctrl+C to stop all services."

# Trap Ctrl+C to gracefully shut down both background processes
trap "echo 'Stopping services...'; kill $GATEWAY_PID $TELEGRAM_PID 2>/dev/null; exit" SIGINT SIGTERM

# Wait for background processes to keep the script running
wait
