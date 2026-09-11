"""
Local testing harness for gateway_app.py.

This does two things:

1. Runs a tiny mock "Android SMS gateway" server that gateway_app.py's
   send_sms_reply() will POST outbound replies to. Instead of actually
   sending a text, it just prints the reply to your terminal. Point
   ANDROID_GATEWAY_URL at this server's /send endpoint in your .env.

2. Provides a CLI to fire simulated *inbound* texts at gateway_app.py's
   /webhook/inbound-sms endpoint, so you can test the whole command set
   (REGISTER, BET, JOIN, VOTE, etc.) without a real phone or Twilio account.

Usage:
    # Terminal 1: run the real app
    uvicorn gateway_app:app --reload --port 8000

    # Terminal 2: run this mock gateway (receives outbound replies)
    python local_twilio.py serve

    # Terminal 3: simulate inbound texts
    python local_twilio.py text +15555550123 "REGISTER bc1qexampleaddressxxxxxxxxxxxxxxxxxxxxxxxx"
    python local_twilio.py text +15555550123 "BET 50 cash Seahawks beat the Broncos"
    python local_twilio.py text +15555550123 "HELP"
"""

import sys
import httpx
from fastapi import FastAPI, Request
import uvicorn

MOCK_GATEWAY_PORT = 8081
GATEWAY_APP_URL = "http://127.0.0.1:8090/webhook/inbound-sms"

mock_app = FastAPI(title="Mock Android SMS Gateway (local testing only)")


@mock_app.post("/send")
async def mock_send(request: Request):
    """Stands in for the real Android gateway. Prints what would have
    been texted out instead of actually sending an SMS."""
    payload = await request.json()
    to = payload.get("to", "unknown")
    message = payload.get("message", "")
    print(f"\n[MOCK OUTBOUND SMS -> {to}]\n{message}\n")
    return {"status": "mock_sent"}


def run_server():
    print(f"[LOCAL TWILIO] Mock SMS gateway listening on http://127.0.0.1:{MOCK_GATEWAY_PORT}")
    print("[LOCAL TWILIO] Set ANDROID_GATEWAY_URL=http://127.0.0.1:8081/send in your .env")
    uvicorn.run(mock_app, host="127.0.0.1", port=MOCK_GATEWAY_PORT)


def send_test_text(sender: str, message: str):
    """Fires a simulated inbound SMS directly at gateway_app.py, bypassing
    Twilio entirely. Useful for fast local iteration on command parsing."""
    try:
        resp = httpx.post(GATEWAY_APP_URL, json={"sender": sender, "message": message}, timeout=30.0)
        print(f"[STATUS {resp.status_code}] {resp.json()}")
    except httpx.ConnectError:
        print(f"[ERROR] Could not reach {GATEWAY_APP_URL} -- is gateway_app.py running (uvicorn gateway_app:app --port 8000)?")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]

    if command == "serve":
        run_server()
    elif command == "text":
        if len(sys.argv) < 4:
            print("Usage: python local_twilio.py text <phone_number> <message>")
            sys.exit(1)
        phone = sys.argv[2]
        message = " ".join(sys.argv[3:])
        send_test_text(phone, message)
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)

