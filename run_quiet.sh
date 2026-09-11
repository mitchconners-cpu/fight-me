#!/usr/bin/env bash
set -e

QUIET=false
for arg in "$@"; do
    case $arg in
        --quiet)
            QUIET=true
            shift
            ;;
    esac
done

PROJECT_ROOT="$(pwd)"
VENV_DIR="$PROJECT_ROOT/venv"
LOG_DIR="$PROJECT_ROOT/logs"

mkdir -p "$LOG_DIR"

if [ "$QUIET" = true ]; then
    exec > >(tee -a "$LOG_DIR/runnel.log") 2>&1
    echo "===== STARTING FASTAPI APP IN BACKGROUND (--quiet) ====="
else
    echo "===== STARTING FASTAPI APP LOCALLY ====="
fi

# 1. Setup or verify virtual environment
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

echo "Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# 2. Install dependencies
if [ -f "requirements.txt" ]; then
    echo "Installing dependencies..."
    pip install --upgrade pip > /dev/null 2>&1 || pip install --upgrade pip
    pip install -r requirements.txt > /dev/null 2>&1 || pip install -r requirements.txt
fi

# 3. Environment file setup
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
fi

# 4. Start FastAPI application using Uvicorn
echo "Launching FastAPI server..."

if [ "$QUIET" = true ]; then
    uvicorn gateway_app:app --host 0.0.0.0 --port 8000 > "$LOG_DIR/fastapi.log" 2>&1 &
    echo $! > "$PROJECT_ROOT/app.pid"
    echo "FastAPI server running in background. PID: $(cat "$PROJECT_ROOT/app.pid")"
    echo "Logs: logs/fastapi.log"
else
    uvicorn gateway_app:app --reload --host 0.0.0.0 --port 8000
fi
