PROJECT="$HOME/sms_app2/project"
HOST="0.0.0.0"
PORT="8000"

SERVER_PID=""
NGROK_PID=""

echo
echo "=============================================="
echo " Anonymous Texting + Wagering App"
echo "=============================================="
echo

cd "$PROJECT" || exit 1

echo "[1] Project:"
echo "    $PWD"
echo

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

echo "[2] Python:"
python --version
echo "    $(which python)"
echo

echo "[3] Checking dependencies..."

if [ -f "$PROJECT/requirements.txt" ]; then
    python -m pip install -r "$PROJECT/requirements.txt"
else
    python -m pip install fastapi "uvicorn[standard]" aiosqlite requests python-dotenv pydantic
fi

echo

echo "[4] Checking application..."

if [ -f "$PROJECT/local_twilio.py" ]; then
    echo "    local_twilio.py found."
else
    echo "    ERROR: local_twilio.py not found."
    echo "    Expected:"
    echo "    $PROJECT/local_twilio.py"
    exit 1
fi

echo
echo "[5] Checking port $PORT..."

OLD_PIDS=$(lsof -ti :"$PORT" 2>/dev/null)

if [ -n "$OLD_PIDS" ]; then
    echo "    Stopping existing process:"
    echo "    $OLD_PIDS"

    for PID in $OLD_PIDS; do
        kill "$PID" 2>/dev/null
    done

    sleep 1

    OLD_PIDS=$(lsof -ti :"$PORT" 2>/dev/null)

    if [ -n "$OLD_PIDS" ]; then
        for PID in $OLD_PIDS; do
            kill -9 "$PID" 2>/dev/null
        done
    fi
fi

echo "    Port $PORT is available."

cleanup() {
    echo
    echo "=============================================="
    echo " Stopping application"
    echo "=============================================="

    if [ -n "$NGROK_PID" ]; then
        kill "$NGROK_PID" 2>/dev/null
    fi

    if [ -n "$SERVER_PID" ]; then
        kill "$SERVER_PID" 2>/dev/null
    fi

    sleep 1

    REMAINING=$(lsof -ti :"$PORT" 2>/dev/null)

    if [ -n "$REMAINING" ]; then
        for PID in $REMAINING; do
            kill "$PID" 2>/dev/null
        done
    fi

    echo "Application stopped."
}

trap cleanup INT TERM EXIT

echo
echo "[6] Starting FastAPI..."

python -m uvicorn gateway_app:app     --host "$HOST"     --port "$PORT"     --reload     > "$PROJECT/uvicorn.log" 2>&1 &

SERVER_PID=$!

sleep 3

SERVER_CHECK=$(ps -p "$SERVER_PID" -o pid= 2>/dev/null)

if [ -z "$SERVER_CHECK" ]; then
    echo
    echo "ERROR: FastAPI failed to start."
    echo
    echo "Server log:"
    tail -50 "$PROJECT/uvicorn.log"
    exit 1
fi

echo "    FastAPI running."
echo "    PID: $SERVER_PID"
echo "    http://127.0.0.1:$PORT"

echo
echo "[7] Starting ngrok..."

if command -v ngrok >/dev/null 2>&1; then

    ngrok http "$PORT" > "$PROJECT/ngrok.log" 2>&1 &
    NGROK_PID=$!

    sleep 3

    NGROK_CHECK=$(ps -p "$NGROK_PID" -o pid= 2>/dev/null)

    if [ -n "$NGROK_CHECK" ]; then
        echo "    ngrok running."
        echo "    PID: $NGROK_PID"
        echo
        echo "    ngrok dashboard:"
        echo "    http://127.0.0.1:4040"
    else
        echo "    WARNING: ngrok failed to start."
        echo
        tail -30 "$PROJECT/ngrok.log"
    fi

else

    echo
    echo "    WARNING: ngrok is not installed."
    echo
    echo "    Install it with:"
    echo "    brew install ngrok"

fi

echo
echo "=============================================="
echo " APPLICATION RUNNING"
echo "=============================================="
echo
echo "Local application:"
echo "    http://127.0.0.1:$PORT"
echo
echo "FastAPI log:"
echo "    $PROJECT/uvicorn.log"
echo
echo "ngrok log:"
echo "    $PROJECT/ngrok.log"
echo
echo "ngrok dashboard:"
echo "    http://127.0.0.1:4040"
echo
echo "Press Ctrl+C to stop FastAPI and ngrok."
echo

wait "$SERVER_PID"
