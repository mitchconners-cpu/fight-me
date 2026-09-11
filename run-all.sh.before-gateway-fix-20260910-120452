#!/bin/bash
# run-all.sh
# Master launcher: venv + deps + FastAPI (local_twilio:app) + ngrok + Telegram bot listener.
# Combines app-start.sh and bot-listener.sh into one process group with shared cleanup.

set -uo pipefail

# Resolve project dir to wherever this script actually lives (portable).
PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST="0.0.0.0"
PORT="8000"

SERVER_PID=""
NGROK_PID=""
BOT_PID=""

echo
echo "=============================================="
echo " Anonymous Texting + Wagering App — Full Stack"
echo "=============================================="
echo

cd "$PROJECT" || exit 1
echo "[1] Project: $PWD"
echo

# --- venv ---
if [ -f "$PROJECT/bin/activate" ]; then
    VENV="$PROJECT/bin/activate"
elif [ -f "$PROJECT/.venv/bin/activate" ]; then
    VENV="$PROJECT/.venv/bin/activate"
elif [ -f "$PROJECT/venv/bin/activate" ]; then
    VENV="$PROJECT/venv/bin/activate"
else
    echo "[2] Creating virtual environment..."
    python3 -m venv "$PROJECT/.venv" || exit 1
    VENV="$PROJECT/.venv/bin/activate"
fi
source "$VENV"

echo "[2] Python: $(python --version) ($(which python))"
echo

# --- deps ---
echo "[3] Checking dependencies..."
if [ -f "$PROJECT/requirements.txt" ]; then
    python -m pip install -r "$PROJECT/requirements.txt"
else
    python -m pip install fastapi "uvicorn[standard]" aiosqlite requests python-dotenv pydantic
fi
echo

# --- sanity check on required tools for the bot listener ---
echo "[4] Checking required tools..."
for tool in curl jq sqlite3; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "    WARNING: '$tool' not found — bot-listener.sh needs it. Install with: brew install $tool"
    fi
done

if [ ! -f "$PROJECT/gateway_app.py" ]; then
    echo "    ERROR: gateway_app.py not found at $PROJECT/gateway_app.py"
    exit 1
fi
if [ ! -f "$PROJECT/bot-listener.sh" ]; then
    echo "    ERROR: bot-listener.sh not found at $PROJECT/bot-listener.sh"
    exit 1
fi
echo "    OK."
echo

# --- free the port ---
echo "[5] Checking port $PORT..."
OLD_PIDS=$(lsof -ti :"$PORT" 2>/dev/null)
if [ -n "$OLD_PIDS" ]; then
    echo "    Stopping existing process(es): $OLD_PIDS"
    for PID in $OLD_PIDS; do kill "$PID" 2>/dev/null; done
    sleep 1
    OLD_PIDS=$(lsof -ti :"$PORT" 2>/dev/null)
    if [ -n "$OLD_PIDS" ]; then
        for PID in $OLD_PIDS; do kill -9 "$PID" 2>/dev/null; done
    fi
fi
echo "    Port $PORT is available."
echo

# --- cleanup on exit ---
cleanup() {
    echo
    echo "=============================================="
    echo " Stopping application"
    echo "=============================================="

    [ -n "$BOT_PID" ] && kill "$BOT_PID" 2>/dev/null
    [ -n "$NGROK_PID" ] && kill "$NGROK_PID" 2>/dev/null
    [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null

    sleep 1
    REMAINING=$(lsof -ti :"$PORT" 2>/dev/null)
    if [ -n "$REMAINING" ]; then
        for PID in $REMAINING; do kill "$PID" 2>/dev/null; done
    fi

    echo "Application stopped."
}
trap cleanup INT TERM EXIT

# --- start FastAPI ---
echo "[6] Starting FastAPI (gateway_app:app)..."
python -m uvicorn gateway_app:app \
    --host "$HOST" \
    --port "$PORT" \
    --reload \
    > "$PROJECT/uvicorn.log" 2>&1 &
SERVER_PID=$!
sleep 3

if [ -z "$(ps -p "$SERVER_PID" -o pid= 2>/dev/null)" ]; then
    echo "ERROR: FastAPI failed to start. Last 50 lines of uvicorn.log:"
    tail -50 "$PROJECT/uvicorn.log"
    exit 1
fi
echo "    FastAPI running. PID: $SERVER_PID  http://127.0.0.1:$PORT"
echo

# --- start ngrok ---
echo "[7] Starting ngrok..."
NGROK_URL=""
if command -v ngrok >/dev/null 2>&1; then
    ngrok http "$PORT" > "$PROJECT/ngrok.log" 2>&1 &
    NGROK_PID=$!
    sleep 3

    if [ -n "$(ps -p "$NGROK_PID" -o pid= 2>/dev/null)" ]; then
        echo "    ngrok running. PID: $NGROK_PID  (dashboard: http://127.0.0.1:4040)"

        # Pull the public https URL from ngrok's local API so bot-listener.sh
        # doesn't need manual editing every restart.
        for i in 1 2 3 4 5; do
            NGROK_URL=$(curl -s http://127.0.0.1:4040/api/tunnels \
                | python -c "import sys,json; d=json.load(sys.stdin); print(next((t['public_url'] for t in d['tunnels'] if t['public_url'].startswith('https')), ''))" 2>/dev/null)
            [ -n "$NGROK_URL" ] && break
            sleep 1
        done

        if [ -n "$NGROK_URL" ]; then
            echo "    Public URL: $NGROK_URL"
        else
            echo "    WARNING: could not read ngrok public URL from API. bot-listener.sh will use its own fallback."
        fi
    else
        echo "    WARNING: ngrok failed to start."
        tail -30 "$PROJECT/ngrok.log"
    fi
else
    echo "    WARNING: ngrok is not installed. Install with: brew install ngrok"
fi
echo

# --- start Telegram bot listener ---
echo "[8] Starting Telegram bot listener..."
# NOTE: bot-listener.sh must read WEB_URL from the environment if set. If it
# currently hardcodes WEB_URL="https://YOUR-NGROK-SUBDOMAIN...", change that
# line to:  WEB_URL="${WEB_URL:-https://YOUR-NGROK-SUBDOMAIN.ngrok-free.app}"
chmod +x "$PROJECT/bot-listener.sh"
WEB_URL="$NGROK_URL" "$PROJECT/bot-listener.sh" > "$PROJECT/bot-listener.log" 2>&1 &
BOT_PID=$!
sleep 1

if [ -z "$(ps -p "$BOT_PID" -o pid= 2>/dev/null)" ]; then
    echo "    WARNING: bot-listener.sh exited immediately. Check bot-listener.log:"
    tail -30 "$PROJECT/bot-listener.log"
else
    echo "    Bot listener running. PID: $BOT_PID"
fi
echo

echo "=============================================="
echo " APPLICATION RUNNING"
echo "=============================================="
echo "  FastAPI:      http://127.0.0.1:$PORT   (log: uvicorn.log)"
echo "  Public URL:   ${NGROK_URL:-not detected}   (log: ngrok.log)"
echo "  Telegram bot: PID $BOT_PID   (log: bot-listener.log)"
echo
echo "Press Ctrl+C to stop everything."
echo

wait "$SERVER_PID"
