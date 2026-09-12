"""
FastAPI Gateway Application Module (`gateway_app.py`).
Backend gateway handling escrow creation, deposit webhooks, HTML dashboards, and chat.
"""

import os
import sqlite3
import logging
from typing import Any, Dict
import httpx
from fastapi import FastAPI, HTTPException, Request, status, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

app = FastAPI(
    title="Wager Escrow Gateway API",
    description="Backend gateway handling escrow creation, deposit webhooks, HTML dashboards, and chat.",
    version="1.1.0",
)

DB_PATH: str = "project.db"
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "6072065878")

templates = Jinja2Templates(directory="templates")
logger = logging.getLogger("gateway_app")

def init_db():
    """Ensure project.db contains necessary tables including chat messages."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bet_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bet_id TEXT,
            sender_address TEXT,
            message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

@app.get("/", response_class=HTMLResponse)
async def render_dashboard(request: Request):
    """Render the live HTML browser dashboard displaying all bets from project.db."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT bet_id, status, wager_amount_sats, escrow_address, created_at FROM bets ORDER BY created_at DESC")
        bets = [dict(row) for row in cursor.fetchall()]
        conn.close()
    except Exception as e:
        logger.error("Database query failed: %s", e)
        bets = []
        
    return templates.TemplateResponse("index.html", {"request": request, "bets": bets})

@app.get("/hub", response_class=HTMLResponse)
async def render_betting_hub(request: Request):
    """Render the primary betting hub with auth, create/join flows, and chat."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT bet_id, status, wager_amount_sats, escrow_address, created_at FROM bets ORDER BY created_at DESC")
        bets = [dict(row) for row in cursor.fetchall()]
        conn.close()
    except Exception as e:
        logger.error("Database query failed: %s", e)
        bets = []
        
    return templates.TemplateResponse("hub.html", {"request": request, "bets": bets})

@app.post("/api/v1/chat/send", status_code=status.HTTP_200_OK)
async def send_chat_message(bet_id: str = Form(...), sender_address: str = Form(...), message: str = Form(...)):
    """Post a chat message for a specific wager session."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO bet_messages (bet_id, sender_address, message) VALUES (?, ?, ?)",
        (bet_id, sender_address, message)
    )
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.get("/api/v1/chat/{bet_id}")
async def get_chat_messages(bet_id: str):
    """Fetch chat messages for a specific wager session."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT sender_address, message, created_at FROM bet_messages WHERE bet_id = ? ORDER BY id ASC", (bet_id,))
    messages = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {"messages": messages}
