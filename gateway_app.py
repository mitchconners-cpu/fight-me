import hashlib
import json
import os
import re
import uuid
from contextlib import asynccontextmanager

import aiosqlite
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Form, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ==========================================
# ==========================================
import httpx

async def send_sms_reply(recipient_phone: str, text: str):
    if str(recipient_phone).startswith("tg_"):
        telegram_chat_id = recipient_phone.replace("tg_", "")
        p1 = "8881701685"
        p2 = "AAEmoCt9YDdT8XGsoG4qEVei_RGHbNm4Eu4"
        url = "https://telegram.org" + p1 + ":" + p2 + "/sendMessage"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json={"chat_id": telegram_chat_id, "text": text}, timeout=10.0)
                if response.status_code == 200:
                    print(f"[TELEGRAM SUCCESS] Sent directly to chat {telegram_chat_id}")
                    return {"status": "telegram_sent"}
            except Exception as e:
                print(f"[TELEGRAM CRITICAL] Loop failed: {e}")
        return {"status": "telegram_failed"}
    
    # Fallback to your mock gateway setup on 8081
    try:
        async with httpx.AsyncClient() as client:
            await client.post("http://127.0.0", json={"to": recipient_phone, "message": text}, timeout=5.0)
    except Exception:
        pass
    print(f"[SMS MOCK FALLBACK -> {recipient_phone}]: {text}")
    return {"status": "mock_sent"}

from twilio.request_validator import RequestValidator

load_dotenv()

# --- CONFIGURATION & ENV SETUP ---
SALT = os.getenv("PROJECT_CRYPTO_SALT")
if not SALT:
    raise ValueError("CRITICAL: PROJECT_CRYPTO_SALT is missing from your .env file!")

OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434/api/generate")
DB_FILE = "project.db"
ANDROID_GATEWAY_URL = os.getenv("ANDROID_GATEWAY_URL", "http://192.168.1.100:8080/send")
REQUIRED_COMMUNITY_APPROVALS = 3
LOGIN_FEE_SATS = int(os.getenv("LOGIN_FEE_SATS", "1000"))
PLATFORM_COMMUNITY_WALLETS = {
    "BTC_MAIN": os.getenv("COMPANY_BTC_ESCROW_ADDRESS", "bc1q_community_escrow_master_wallet"),
    "FEE_COLLECTOR": os.getenv("COMPANY_BTC_FEE_ADDRESS", "bc1q_platform_entry_fee_wallet"),
}

# Twilio auth token, required to validate that inbound webhook requests
# actually originated from Twilio and not a forged POST from anyone who
# finds your webhook URL.
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
twilio_validator = RequestValidator(TWILIO_AUTH_TOKEN) if TWILIO_AUTH_TOKEN else None

# Basic BTC address sanity check (legacy/P2SH/bech32). Not exhaustive
# validation of checksum, just enough to reject obvious garbage input
# before it becomes someone's permanent identity.
BTC_ADDRESS_RE = re.compile(r"^(bc1[a-zA-HJ-NP-Z0-9]{25,62}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$")


# --- HELPER UTILITIES ---
async def fetch_current_btc_price_usd() -> float:
    """Fetch live spot price for BTC/USD from Coinbase."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get("https://api.coinbase.com/v2/prices/BTC-USD/spot")
            if res.status_code == 200:
                data = res.json()
                return float(data["data"]["amount"])
    except Exception as e:
        print(f"[PRICE API WARNING] Could not fetch live price: {e}")
    return 95000.0  # Safe fallback estimate if offline


def convert_to_sats(amount: float, currency: str, btc_price_usd: float) -> int:
    """Convert BTC, USD, or SATS input into Satoshis."""
    currency = currency.upper()
    if currency == "SATS":
        return int(amount)
    elif currency == "BTC":
        return int(amount * 100_000_000)
    elif currency in ["USD", "CASH"]:
        if btc_price_usd <= 0:
            btc_price_usd = 95000.0
        btc_value = amount / btc_price_usd
        return int(btc_value * 100_000_000)
    return int(amount)


def anonymize_user_id(raw_identifier: str) -> str:
    return hashlib.sha256((raw_identifier.strip() + SALT).encode("utf-8")).hexdigest()


def scrub_sensitive_data(text: str) -> str:
    text = re.sub(r"[\w\.-]+@[\w\.-]+\.\w+", "[REDACTED_EMAIL]", text)
    text = re.sub(r"(\+\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", "[REDACTED_PHONE]", text)
    return text


def is_valid_btc_address(addr: str) -> bool:
    return bool(BTC_ADDRESS_RE.match(addr.strip()))


async def check_address_funded(address: str, expected_sats: int) -> bool:
    """
    Pluggable on-chain funding check. Stubbed against mempool.space's public
    API for now -- swap this out for your own node/indexer before going live,
    since public explorers rate-limit and shouldn't be trusted as your only
    source of truth for real money.
    """
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            res = await client.get(f"https://mempool.space/api/address/{address}")
            if res.status_code != 200:
                return False
            data = res.json()
            funded_sats = data.get("chain_stats", {}).get("funded_txo_sum", 0)
            return funded_sats >= expected_sats
    except Exception as e:
        print(f"[FUNDING CHECK WARNING] Could not verify {address}: {e}")
        return False


# --- SMS MESSAGE TREE (numbered menu navigation) ---
MENU_GUEST = "MENU_GUEST"
MENU_REGISTERED = "MENU_REGISTERED"

MENU_TEXT = {
    MENU_GUEST: (
        "Welcome to BTC Wagers! Anyone can bet on anything -- your BTC "
        "address is your identity. Reply with a number:\n"
        "1) How it works\n"
        "2) See open bets\n"
        "3) Register my BTC address\n"
        "4) Full command list"
    ),
    MENU_REGISTERED: (
        "Welcome back! Reply with a number:\n"
        "1) How it works\n"
        "2) See open bets\n"
        "3) Create a bet\n"
        "4) My bets\n"
        "5) Full command list"
    ),
}

HOW_IT_WORKS_TEXT = (
    "How it works:\n"
    "1. Register your BTC address (your permanent ID)\n"
    f"2. Pay a one-time {LOGIN_FEE_SATS} sat entry fee\n"
    "3. Create a wager or join an open one\n"
    "4. Both sides send their wager to escrow\n"
    "5. After the outcome, both sides vote on the winner. "
    "If you agree, it pays out. If you disagree, a community "
    "panel resolves it.\n"
    "Text MENU anytime to come back here."
)

FULL_COMMAND_LIST_TEXT = (
    "Full command list:\n"
    "REGISTER <btc_addr> -- link your identity\n"
    "PRICE -- live BTC price\n"
    "LIST -- open wagers\n"
    "BET <amount> <unit> <terms> -- create a wager\n"
    "ADDR <bet_id> <btc_addr> -- set your payout address\n"
    "JOIN <bet_id> <btc_addr> -- accept a wager\n"
    "MYBETS -- wagers you're part of\n"
    "VOTE <bet_id> <winner_token> -- submit outcome\n"
    "APPROVE <bet_id> <winner_token> -- community vote on a dispute\n"
    "MENU -- show this menu system again"
)

MENU_TRIGGER_WORDS = {"HI", "HELLO", "HEY", "MENU", "START", "0"}


async def get_menu_state(db: aiosqlite.Connection, phone: str):
    phone_hash = anonymize_user_id(phone)
    db.row_factory = aiosqlite.Row
    async with db.execute(
        "SELECT menu FROM sms_menu_state WHERE phone_hash = ?", (phone_hash,)
    ) as cursor:
        row = await cursor.fetchone()
    return row["menu"] if row else None


async def set_menu_state(db: aiosqlite.Connection, phone: str, menu: str):
    phone_hash = anonymize_user_id(phone)
    await db.execute(
        """
        INSERT INTO sms_menu_state (phone_hash, menu, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(phone_hash) DO UPDATE SET menu = excluded.menu, updated_at = CURRENT_TIMESTAMP
        """,
        (phone_hash, menu),
    )
    await db.commit()


async def clear_menu_state(db: aiosqlite.Connection, phone: str):
    phone_hash = anonymize_user_id(phone)
    await db.execute("DELETE FROM sms_menu_state WHERE phone_hash = ?", (phone_hash,))
    await db.commit()


async def build_open_bets_text() -> str:
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT bet_id, wager_amount, currency, terms FROM bets WHERE status = 'PENDING_ACCEPTANCE' LIMIT 5"
        ) as cursor:
            open_bets = await cursor.fetchall()

    if not open_bets:
        return "No open wagers right now. Text 'BET 50 cash <terms>' to start one!"
    return "Open Wagers:\n" + "\n".join(
        f"- {b['bet_id']}: {b['wager_amount']} {b['currency']} - {b['terms'][:30]}" for b in open_bets
    ) + "\nText JOIN <bet_id> <btc_addr> to accept."


async def build_my_bets_text(token: str) -> str:
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT bet_id, terms, status FROM bets
               WHERE creator_token = ? OR opponent_token = ?
               ORDER BY created_at DESC LIMIT 5""",
            (token, token)
        ) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        return "You have no wagers yet. Text 'BET 50 cash <terms>' to start one!"
    return "Your Wagers:\n" + "\n".join(
        f"- {r['bet_id']} [{r['status']}]: {r['terms'][:30]}" for r in rows
    )


async def handle_menu_navigation(sender: str, clean_message: str, identity: dict):
    """
    Returns a reply string if this message was handled as menu navigation
    (a trigger word or a numeric reply to an active menu), otherwise None
    so the caller falls through to normal command parsing.
    """
    uppercase_cmd = clean_message.upper()
    home_menu = MENU_REGISTERED if identity["registered"] else MENU_GUEST

    async with aiosqlite.connect(DB_FILE) as db:
        current_menu = await get_menu_state(db, sender)

        # Explicit trigger words always (re)open the appropriate home menu.
        if uppercase_cmd in MENU_TRIGGER_WORDS:
            await set_menu_state(db, sender, home_menu)
            return MENU_TEXT[home_menu]

        # Not currently in a menu and didn't ask for one -> let normal
        # command parsing take a shot at this message first.
        if not current_menu or not clean_message.strip().isdigit():
            return None

        choice = clean_message.strip()

        if current_menu == MENU_GUEST:
            if choice == "1":
                return HOW_IT_WORKS_TEXT
            if choice == "2":
                return await build_open_bets_text()
            if choice == "3":
                await clear_menu_state(db, sender)
                return "Text: REGISTER <your_btc_address>\nExample: REGISTER bc1qexample..."
            if choice == "4":
                return FULL_COMMAND_LIST_TEXT
            return "Not a valid option. " + MENU_TEXT[MENU_GUEST]

        if current_menu == MENU_REGISTERED:
            if choice == "1":
                return HOW_IT_WORKS_TEXT
            if choice == "2":
                return await build_open_bets_text()
            if choice == "3":
                await clear_menu_state(db, sender)
                return "Text: BET <amount> <unit> <terms>\nExample: BET 50 cash Seahawks win Sunday"
            if choice == "4":
                return await build_my_bets_text(identity["token"])
            if choice == "5":
                return FULL_COMMAND_LIST_TEXT
            return "Not a valid option. " + MENU_TEXT[MENU_REGISTERED]

    return None


# --- IDENTITY RESOLUTION (the core fix) ---
async def resolve_identity(db: aiosqlite.Connection, phone: str) -> dict:
    """
    Every inbound SMS, regardless of command, must resolve through here.
    Returns a dict describing whether this phone is linked to a registered
    BTC-address identity yet.

    - If linked: token is anonymize_user_id(btc_address) -- the SAME token
      the web dashboard uses for that address. This is what lets someone
      text in a bet and later see/manage it from the web console.
    - If not linked: token is a temporary phone-based token, and the caller
      should push the user toward REGISTER <btc_address>.
    """
    db.row_factory = aiosqlite.Row
    phone_hash = anonymize_user_id(phone)

    async with db.execute(
        "SELECT btc_address FROM phone_links WHERE phone_hash = ?", (phone_hash,)
    ) as cursor:
        row = await cursor.fetchone()

    if row:
        btc_address = row["btc_address"]
        return {
            "registered": True,
            "token": anonymize_user_id(btc_address),
            "btc_address": btc_address,
        }

    return {
        "registered": False,
        "token": phone_hash,
        "btc_address": None,
    }


async def link_phone_to_address(db: aiosqlite.Connection, phone: str, btc_address: str):
    phone_hash = anonymize_user_id(phone)
    user_token = anonymize_user_id(btc_address)

    await db.execute(
        """
        INSERT INTO phone_links (phone_hash, btc_address) VALUES (?, ?)
        ON CONFLICT(phone_hash) DO UPDATE SET btc_address = excluded.btc_address
        """,
        (phone_hash, btc_address),
    )
    await db.execute(
        "INSERT OR IGNORE INTO users (user_token, btc_address, has_paid_login_fee) VALUES (?, ?, 0)",
        (user_token, btc_address),
    )
    await db.commit()


# --- DATABASE INITIALIZATION & AUTO-MIGRATION ENGINE ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("PRAGMA foreign_keys = ON;")

        # Users Table -- keyed by BTC address, always the canonical identity
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_token TEXT PRIMARY KEY,
                btc_address TEXT UNIQUE NOT NULL,
                has_paid_login_fee INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_login_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Phone -> BTC address linking table. This is the piece that unifies
        # SMS and web identities. phone_hash is anonymize_user_id(raw_phone).
        await db.execute("""
            CREATE TABLE IF NOT EXISTS phone_links (
                phone_hash TEXT PRIMARY KEY,
                btc_address TEXT NOT NULL,
                linked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (btc_address) REFERENCES users(btc_address)
            )
        """)

        # Tracks which numbered menu (if any) a phone number is currently
        # looking at, so a bare "2" reply can be interpreted correctly.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sms_menu_state (
                phone_hash TEXT PRIMARY KEY,
                menu TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Chat History Table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT NOT NULL,
                role TEXT NOT NULL,
                message TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Wagers Table (Multi-Currency & Non-Unique Escrow)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bets (
                bet_id TEXT PRIMARY KEY,
                creator_token TEXT NOT NULL,
                opponent_token TEXT,
                terms TEXT NOT NULL,
                currency TEXT DEFAULT 'SATS',
                wager_amount REAL NOT NULL,
                wager_amount_sats INTEGER NOT NULL,
                total_pool_sats INTEGER NOT NULL DEFAULT 0,
                platform_fee_sats INTEGER NOT NULL DEFAULT 0,
                winner_payout_sats INTEGER NOT NULL DEFAULT 0,
                escrow_address TEXT,
                creator_vote TEXT,
                opponent_vote TEXT,
                winner_token TEXT,
                status TEXT DEFAULT 'PENDING_ACCEPTANCE',
                approvals_count INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                resolved_at DATETIME
            )
        """)

        # Bet Participants Table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bet_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bet_id TEXT NOT NULL,
                user_token TEXT NOT NULL,
                role TEXT CHECK(role IN ('CREATOR', 'OPPONENT')),
                deposit_address TEXT,
                payout_wallet_address TEXT,
                is_funded INTEGER DEFAULT 0,
                FOREIGN KEY (bet_id) REFERENCES bets(bet_id) ON DELETE CASCADE
            )
        """)

        # Multi-Sig Approvals Table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bet_approvals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bet_id TEXT NOT NULL,
                validator_token TEXT NOT NULL,
                approved_winner_token TEXT NOT NULL,
                approved_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(bet_id, validator_token),
                FOREIGN KEY (bet_id) REFERENCES bets(bet_id) ON DELETE CASCADE
            )
        """)

        # Schema Auto-Migration Guard: Add missing columns if database exists from prior versions
        async with db.execute("PRAGMA table_info(bets)") as cursor:
            existing_columns = [row[1] for row in await cursor.fetchall()]

        columns_to_add = {
            "currency": "TEXT DEFAULT 'SATS'",
            "wager_amount": "REAL DEFAULT 0",
            "wager_amount_sats": "INTEGER DEFAULT 0",
            "total_pool_sats": "INTEGER NOT NULL DEFAULT 0",
            "platform_fee_sats": "INTEGER NOT NULL DEFAULT 0",
            "winner_payout_sats": "INTEGER NOT NULL DEFAULT 0",
            "escrow_address": "TEXT",
        }

        for col_name, col_type in columns_to_add.items():
            if col_name not in existing_columns:
                await db.execute(f"ALTER TABLE bets ADD COLUMN {col_name} {col_type};")

        await db.commit()
    print("[SYSTEM LOG] Communication Stack, Database Engine & SMS Gateway Ready.")
    yield


app = FastAPI(title="Self-Hosted FOSS Twilio & BTC Bet Gateway", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


# --- PYDANTIC REQUEST SCHEMAS ---
class BTCLoginRequest(BaseModel):
    btc_address: str

class CreateBetRequest(BaseModel):
    creator_identifier: str  # BTC address for web-originated bets
    terms: str
    wager_amount: float
    currency: str = "SATS"  # "SATS", "BTC", or "USD"
    payout_address: str

class JoinBetRequest(BaseModel):
    bet_id: str
    opponent_identifier: str
    payout_address: str

class VoteBetRequest(BaseModel):
    bet_id: str
    voter_identifier: str
    voted_winner_token: str

class ApproveBetRequest(BaseModel):
    bet_id: str
    validator_identifier: str
    approved_winner_token: str

class InboundSMS(BaseModel):
    sender: str
    message: str


# --- CORE INTERNAL LOGIC ---
async def create_bet_internal(creator_token: str, terms: str, wager_amount: float, currency: str, payout_address: str):
    """
    NOTE: this now takes an already-resolved creator_token (BTC-address-based),
    not a raw identifier. Callers are responsible for identity resolution --
    see resolve_identity() for SMS, or direct anonymize_user_id(btc_address)
    for the web API.
    """
    bet_id = f"BET-{uuid.uuid4().hex[:8].upper()}"

    btc_price = await fetch_current_btc_price_usd()
    wager_sats = convert_to_sats(wager_amount, currency, btc_price)

    total_pool = wager_sats * 2
    platform_fee = int(total_pool * 0.10)
    winner_payout = total_pool - platform_fee
    escrow_address = PLATFORM_COMMUNITY_WALLETS["BTC_MAIN"]

    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            """
            INSERT INTO bets (
                bet_id, creator_token, terms, currency, wager_amount, wager_amount_sats,
                total_pool_sats, platform_fee_sats, winner_payout_sats,
                escrow_address, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING_ACCEPTANCE')
            """,
            (bet_id, creator_token, terms, currency.upper(), wager_amount, wager_sats, total_pool, platform_fee, winner_payout, escrow_address)
        )

        await db.execute(
            """
            INSERT INTO bet_participants (bet_id, user_token, role, payout_wallet_address)
            VALUES (?, ?, 'CREATOR', ?)
            """,
            (bet_id, creator_token, payout_address)
        )

        await db.commit()

    return {
        "bet_id": bet_id,
        "terms": terms,
        "currency": currency.upper(),
        "wager_amount": wager_amount,
        "wager_amount_sats": wager_sats,
        "escrow_address": escrow_address,
        "status": "PENDING_ACCEPTANCE"
    }


# --- WEB DASHBOARD ROUTING ---
@app.get("/")
@app.get("/console")
async def serve_dashboard():
    if os.path.exists("static/index.html"):
        return FileResponse("static/index.html")
    return JSONResponse(status_code=404, content={"detail": "static/index.html not found."})


# --- API ENDPOINTS ---
@app.get("/api/btc-price")
async def get_btc_price():
    price_usd = await fetch_current_btc_price_usd()
    return {
        "currency": "USD",
        "price_usd": price_usd,
        "sats_per_dollar": int(100_000_000 / price_usd) if price_usd > 0 else 0
    }


@app.post("/api/auth/btc-login")
async def btc_login(payload: BTCLoginRequest):
    if not is_valid_btc_address(payload.btc_address):
        raise HTTPException(status_code=400, detail="That doesn't look like a valid BTC address.")

    user_token = anonymize_user_id(payload.btc_address)

    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE btc_address = ?", (payload.btc_address,)) as cursor:
            user = await cursor.fetchone()

        if not user:
            await db.execute(
                "INSERT INTO users (user_token, btc_address, has_paid_login_fee) VALUES (?, ?, 0)",
                (user_token, payload.btc_address)
            )
            await db.commit()
            has_paid = False
        else:
            has_paid = bool(user["has_paid_login_fee"])
            await db.execute("UPDATE users SET last_login_at = CURRENT_TIMESTAMP WHERE user_token = ?", (user_token,))
            await db.commit()

    return {
        "user_token": user_token,
        "btc_address": payload.btc_address,
        "access_granted": has_paid,
        "required_fee_sats": LOGIN_FEE_SATS,
        "fee_deposit_address": PLATFORM_COMMUNITY_WALLETS["FEE_COLLECTOR"]
    }


async def require_paid_access(btc_address: str):
    """Gate that actually enforces LOGIN_FEE_SATS instead of just tracking it."""
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT has_paid_login_fee FROM users WHERE btc_address = ?", (btc_address,)
        ) as cursor:
            user = await cursor.fetchone()

    if not user:
        raise HTTPException(status_code=403, detail="Account not found. Log in with your BTC address first.")
    if not user["has_paid_login_fee"]:
        raise HTTPException(
            status_code=402,
            detail=f"Entry fee required: send {LOGIN_FEE_SATS} sats to {PLATFORM_COMMUNITY_WALLETS['FEE_COLLECTOR']}, "
                   f"then confirm via /api/auth/confirm-fee."
        )


@app.post("/api/auth/confirm-fee")
async def confirm_fee(payload: BTCLoginRequest):
    """
    Checks whether the fee wallet actually received LOGIN_FEE_SATS attributable
    to this user. In production you'd match against a specific memo/amount or
    a per-user deposit address rather than a shared pool address, since a
    shared address can't tell users apart on its own.
    """
    funded = await check_address_funded(PLATFORM_COMMUNITY_WALLETS["FEE_COLLECTOR"], LOGIN_FEE_SATS)
    if not funded:
        return {"status": "pending", "message": "Fee payment not yet detected."}

    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "UPDATE users SET has_paid_login_fee = 1 WHERE btc_address = ?", (payload.btc_address,)
        )
        await db.commit()

    return {"status": "success", "message": "Access granted."}


@app.post("/api/bets/create")
async def create_bet_endpoint(payload: CreateBetRequest):
    if not is_valid_btc_address(payload.creator_identifier):
        raise HTTPException(status_code=400, detail="creator_identifier must be a valid BTC address.")
    await require_paid_access(payload.creator_identifier)

    creator_token = anonymize_user_id(payload.creator_identifier)
    return await create_bet_internal(
        creator_token,
        payload.terms,
        payload.wager_amount,
        payload.currency,
        payload.payout_address
    )


@app.get("/api/bets/list")
async def list_bets():
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT bet_id, creator_token, terms, currency, wager_amount, wager_amount_sats, total_pool_sats, winner_payout_sats, escrow_address, status, approvals_count FROM bets ORDER BY created_at DESC LIMIT 50"
        ) as cursor:
            rows = await cursor.fetchall()

    bets = [dict(row) for row in rows]
    return {"bets": bets}


@app.get("/api/bets/mine")
async def my_bets(btc_address: str):
    """Bets where this BTC-address identity is creator or opponent, regardless
    of whether they were opened via web or SMS -- this only works correctly
    now that both channels share one token derivation."""
    if not is_valid_btc_address(btc_address):
        raise HTTPException(status_code=400, detail="Invalid BTC address.")
    token = anonymize_user_id(btc_address)

    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT bet_id, terms, currency, wager_amount, status, winner_token
               FROM bets WHERE creator_token = ? OR opponent_token = ?
               ORDER BY created_at DESC LIMIT 25""",
            (token, token)
        ) as cursor:
            rows = await cursor.fetchall()

    return {"bets": [dict(row) for row in rows]}


@app.post("/api/bets/join")
async def join_bet(payload: JoinBetRequest):
    if not is_valid_btc_address(payload.opponent_identifier):
        raise HTTPException(status_code=400, detail="opponent_identifier must be a valid BTC address.")
    await require_paid_access(payload.opponent_identifier)

    opponent_token = anonymize_user_id(payload.opponent_identifier)

    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM bets WHERE bet_id = ?", (payload.bet_id,)) as cursor:
            bet = await cursor.fetchone()

        if not bet:
            raise HTTPException(status_code=404, detail="Wager not found.")
        if bet["status"] != "PENDING_ACCEPTANCE":
            raise HTTPException(status_code=400, detail="Wager is no longer open for acceptance.")
        if bet["creator_token"] == opponent_token:
            raise HTTPException(status_code=400, detail="You cannot accept your own wager.")

        await db.execute("UPDATE bets SET opponent_token = ?, status = 'ACTIVE' WHERE bet_id = ?", (opponent_token, payload.bet_id))
        await db.execute(
            "INSERT INTO bet_participants (bet_id, user_token, role, payout_wallet_address) VALUES (?, ?, 'OPPONENT', ?)",
            (payload.bet_id, opponent_token, payload.payout_address)
        )
        await db.commit()

    return {"message": f"Successfully joined wager {payload.bet_id}!", "bet_id": payload.bet_id}


@app.post("/api/bets/vote")
async def vote_bet(payload: VoteBetRequest):
    voter_token = anonymize_user_id(payload.voter_identifier)

    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM bets WHERE bet_id = ?", (payload.bet_id,)) as cursor:
            bet = await cursor.fetchone()

        if not bet:
            raise HTTPException(status_code=404, detail="Wager not found.")
        if bet["status"] == "DISPUTED":
            raise HTTPException(status_code=400, detail="Wager is disputed; resolution now requires community approval, not re-voting.")

        if voter_token == bet["creator_token"]:
            await db.execute("UPDATE bets SET creator_vote = ? WHERE bet_id = ?", (payload.voted_winner_token, payload.bet_id))
        elif voter_token == bet["opponent_token"]:
            await db.execute("UPDATE bets SET opponent_vote = ? WHERE bet_id = ?", (payload.voted_winner_token, payload.bet_id))
        else:
            raise HTTPException(status_code=403, detail="Not a participant in this wager.")

        async with db.execute("SELECT creator_vote, opponent_vote FROM bets WHERE bet_id = ?", (payload.bet_id,)) as cursor:
            updated_bet = await cursor.fetchone()

        c_vote = updated_bet["creator_vote"]
        o_vote = updated_bet["opponent_vote"]

        if c_vote and o_vote:
            if c_vote == o_vote:
                await db.execute(
                    "UPDATE bets SET winner_token = ?, status = 'RESOLVED', resolved_at = CURRENT_TIMESTAMP WHERE bet_id = ?",
                    (c_vote, payload.bet_id)
                )
                msg = "Consensus reached! Wager resolved successfully."
            else:
                await db.execute("UPDATE bets SET status = 'DISPUTED' WHERE bet_id = ?", (payload.bet_id,))
                msg = "Conflicting votes detected! Wager flagged as DISPUTED for multi-sig validation."
        else:
            msg = "Vote recorded. Awaiting second participant vote."

        await db.commit()

    return {"message": msg, "bet_id": payload.bet_id}


@app.post("/api/bets/approve")
async def approve_bet(payload: ApproveBetRequest):
    validator_token = anonymize_user_id(payload.validator_identifier)

    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM bets WHERE bet_id = ?", (payload.bet_id,)) as cursor:
            bet = await cursor.fetchone()

        if not bet:
            raise HTTPException(status_code=404, detail="Wager not found.")
        if bet["status"] != "DISPUTED":
            raise HTTPException(status_code=400, detail="Only disputed wagers require community approval.")

        try:
            await db.execute(
                "INSERT INTO bet_approvals (bet_id, validator_token, approved_winner_token) VALUES (?, ?, ?)",
                (payload.bet_id, validator_token, payload.approved_winner_token)
            )
        except aiosqlite.IntegrityError:
            raise HTTPException(status_code=400, detail="Validator has already voted on this wager.")

        new_count = bet["approvals_count"] + 1
        if new_count >= REQUIRED_COMMUNITY_APPROVALS:
            await db.execute(
                "UPDATE bets SET approvals_count = ?, winner_token = ?, status = 'RESOLVED', resolved_at = CURRENT_TIMESTAMP WHERE bet_id = ?",
                (new_count, payload.approved_winner_token, payload.bet_id)
            )
            msg = "Multi-sig quorum reached! Wager resolved."
        else:
            await db.execute("UPDATE bets SET approvals_count = ? WHERE bet_id = ?", (new_count, payload.bet_id))
            msg = f"Approval recorded ({new_count}/{REQUIRED_COMMUNITY_APPROVALS})."

        await db.commit()

    return {"message": msg, "approvals_count": new_count}


@app.get("/api/info/guide")
async def get_guide():
    return {
        "entry_fee_sats": LOGIN_FEE_SATS,
        "fee_payment_address": PLATFORM_COMMUNITY_WALLETS["FEE_COLLECTOR"],
        "steps": [
            {"step": 1, "name": "BTC Auth", "description": "Authenticate via Bitcoin address (this is your permanent identity across web and SMS)."},
            {"step": 2, "name": "Create/Join", "description": "Launch wagers via web console or SMS in BTC, Cash, or Sats."},
            {"step": 3, "name": "Escrow Funding", "description": "Deposit sats into multi-sig platform wallet."},
            {"step": 4, "name": "Consensus Settlement", "description": "Participants vote; disagreements go to community verifiers."}
        ]
    }


# --- SMS ROUTERS (LOCAL GATEWAY & TWILIO) ---
@app.post("/webhook/twilio-sms")
async def receive_twilio_sms(request: Request, From: str = Form(...), Body: str = Form(...), X_Twilio_Signature: str = Header(None)):
    """Twilio Webhook Handler. Validates the request signature before
    processing anything, so this endpoint can't be puppeted by forged POSTs."""
    if twilio_validator:
        form_data = dict(await request.form())
        url = str(request.url)
        valid = twilio_validator.validate(url, form_data, X_Twilio_Signature or "")
        if not valid:
            raise HTTPException(status_code=403, detail="Invalid Twilio signature.")
    else:
        print("[SECURITY WARNING] TWILIO_AUTH_TOKEN not set -- signature validation is disabled!")

    payload = InboundSMS(sender=From, message=Body)
    await receive_local_carrier_sms(payload)
    return Response(content="<Response></Response>", media_type="application/xml")


@app.post("/webhook/inbound-sms")
async def receive_local_carrier_sms(payload: InboundSMS):
    """Core SMS processing router for both local Android Gateway and Twilio."""
    clean_message = scrub_sensitive_data(payload.message).strip()
    uppercase_cmd = clean_message.upper()

    async with aiosqlite.connect(DB_FILE) as db:
        identity = await resolve_identity(db, payload.sender)

    anonymous_token = identity["token"]

    # 0. REGISTER COMMAND -- links this phone to a BTC-address identity.
    # This must work even before other commands do, since it's the thing
    # that makes every other command "count" toward a real account.
    register_match = re.match(r"^REGISTER\s+(\S+)$", clean_message, re.IGNORECASE)
    if register_match:
        candidate_address = register_match.group(1)
        if not is_valid_btc_address(candidate_address):
            reply = "That doesn't look like a valid BTC address. Text REGISTER <your_btc_address>."
        else:
            async with aiosqlite.connect(DB_FILE) as db:
                await link_phone_to_address(db, payload.sender, candidate_address)
                await set_menu_state(db, payload.sender, MENU_REGISTERED)
            reply = (
                f"Linked! Your identity is now tied to {candidate_address}. "
                f"This works the same whether you text in or use the web console. "
                f"Send {LOGIN_FEE_SATS} sats to {PLATFORM_COMMUNITY_WALLETS['FEE_COLLECTOR']} to activate betting.\n\n"
                + MENU_TEXT[MENU_REGISTERED]
            )
        await send_sms_reply(payload.sender, reply)
        return {"status": "success", "action": "register"}

    # 0.5 MENU NAVIGATION -- trigger words (HI/MENU/START/...) or a bare
    # number while a menu is active. Brand-new texters land here too, since
    # an unrecognized first message from an unregistered phone falls through
    # to this with no active menu state, gets a home-menu render below.
    menu_reply = await handle_menu_navigation(payload.sender, clean_message, identity)
    if menu_reply is not None:
        await send_sms_reply(payload.sender, menu_reply)
        return {"status": "success", "action": "menu"}

    if not identity["registered"]:
        # Let PRICE/HELP/LIST work for guests without registering first, but
        # anything else -- including a totally unrecognized first message --
        # gets the guided welcome menu instead of a blunt rejection.
        if uppercase_cmd not in ["HELP", "GUIDE", "COMMANDS", "PRICE", "BTC", "TICKER", "LIST", "BETS", "OPEN"]:
            async with aiosqlite.connect(DB_FILE) as db:
                await set_menu_state(db, payload.sender, MENU_GUEST)
            reply = MENU_TEXT[MENU_GUEST]
            await send_sms_reply(payload.sender, reply)
            return {"status": "success", "action": "welcome_menu"}

    # 1. HELP / COMMAND GUIDE
    if uppercase_cmd in ["HELP", "GUIDE", "COMMANDS"]:
        reply = (
            "BTC Wagering Commands:\n"
            "• REGISTER <btc_addr>: Link your identity (do this first)\n"
            "• PRICE: Live BTC price\n"
            "• LIST: Show active open wagers\n"
            "• BET <amount> <unit> <terms>: Create wager (e.g. BET 50 cash, BET 0.001 btc, BET 5000 sats)\n"
            "• ADDR <bet_id> <btc_addr>: Set payout address for a bet you created\n"
            "• JOIN <bet_id> <btc_addr>: Accept wager\n"
            "• MYBETS: List wagers you're part of\n"
            "• VOTE <bet_id> <winner_token>: Submit outcome\n"
            "• APPROVE <bet_id> <winner_token>: Community vote on a disputed bet\n"
            "• MENU: Show the numbered menu instead of typing commands"
        )
        await send_sms_reply(payload.sender, reply)
        return {"status": "success", "action": "help"}

    # 2. LIVE PRICE COMMAND
    if uppercase_cmd in ["PRICE", "BTC", "TICKER"]:
        price = await fetch_current_btc_price_usd()
        reply = f"Live BTC Price: ${price:,.2f} USD\n1 USD = {int(100_000_000/price):,} sats"
        await send_sms_reply(payload.sender, reply)
        return {"status": "success", "action": "price"}

    # 3. LIST ACTIVE WAGERS
    if uppercase_cmd in ["LIST", "BETS", "OPEN"]:
        async with aiosqlite.connect(DB_FILE) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT bet_id, wager_amount, currency, terms FROM bets WHERE status = 'PENDING_ACCEPTANCE' LIMIT 5"
            ) as cursor:
                open_bets = await cursor.fetchall()

        if not open_bets:
            reply = "No open wagers available right now. Text 'BET 50 cash <terms>' to start one!"
        else:
            reply = "Open Wagers:\n" + "\n".join(
                [f"• {b['bet_id']}: {b['wager_amount']} {b['currency']} - {b['terms'][:30]}" for b in open_bets]
            ) + "\nText JOIN <bet_id> <btc_addr> to accept."

        await send_sms_reply(payload.sender, reply)
        return {"status": "success", "action": "list_bets"}

    # 4. MYBETS -- now actually meaningful since token is identity-unified
    if uppercase_cmd == "MYBETS":
        async with aiosqlite.connect(DB_FILE) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT bet_id, terms, status FROM bets
                   WHERE creator_token = ? OR opponent_token = ?
                   ORDER BY created_at DESC LIMIT 5""",
                (anonymous_token, anonymous_token)
            ) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            reply = "You have no wagers yet. Text 'BET 50 cash <terms>' to start one!"
        else:
            reply = "Your Wagers:\n" + "\n".join(
                [f"• {r['bet_id']} [{r['status']}]: {r['terms'][:30]}" for r in rows]
            )
        await send_sms_reply(payload.sender, reply)
        return {"status": "success", "action": "my_bets"}

    # 5. CREATE WAGER COMMAND: "BET 50 cash BTC hits 100k" or "BET 0.005 btc BTC hits 100k"
    bet_match = re.match(
        r"^BET\s+\$?([0-9\.]+)\s*(sats|sat|btc|cash|usd)?\s+(.+)$",
        clean_message,
        re.IGNORECASE
    )
    if bet_match:
        wager_amount = float(bet_match.group(1))
        unit = (bet_match.group(2) or "SATS").upper()
        terms = bet_match.group(3)

        if unit in ["CASH", "USD", "$"]:
            currency = "USD"
        elif unit in ["BTC"]:
            currency = "BTC"
        else:
            currency = "SATS"

        # Payout address defaults to the address they registered with; they
        # can override later with ADDR <bet_id> <btc_addr> if needed.
        res = await create_bet_internal(anonymous_token, terms, wager_amount, currency, identity["btc_address"])
        reply = (
            f"Wager Launched!\n"
            f"ID: {res['bet_id']}\n"
            f"Wager: {wager_amount} {res['currency']} ({res['wager_amount_sats']:,} sats)\n"
            f"Escrow Address: {res['escrow_address']}\n"
            f"Payout goes to your registered address. Use ADDR {res['bet_id']} <btc_addr> to change it.\n"
            f"Share ID with opponent to join!"
        )
        await send_sms_reply(payload.sender, reply)
        return {"status": "success", "action": "create_bet", "bet_id": res['bet_id']}

    # 6. ADDR COMMAND -- fixes the SMS_PENDING_ADDRESS placeholder bug by
    # letting the creator set/update their payout address explicitly.
    addr_match = re.match(r"^ADDR\s+(BET-[A-F0-9]{8})\s+(\S+)$", clean_message, re.IGNORECASE)
    if addr_match:
        bet_id = addr_match.group(1).upper()
        new_address = addr_match.group(2)

        if not is_valid_btc_address(new_address):
            reply = "That doesn't look like a valid BTC address."
        else:
            async with aiosqlite.connect(DB_FILE) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM bet_participants WHERE bet_id = ? AND user_token = ?",
                    (bet_id, anonymous_token)
                ) as cursor:
                    participant = await cursor.fetchone()

                if not participant:
                    reply = f"You're not a participant in {bet_id}."
                else:
                    await db.execute(
                        "UPDATE bet_participants SET payout_wallet_address = ? WHERE bet_id = ? AND user_token = ?",
                        (new_address, bet_id, anonymous_token)
                    )
                    await db.commit()
                    reply = f"Payout address for {bet_id} updated to {new_address}."

        await send_sms_reply(payload.sender, reply)
        return {"status": "success", "action": "set_address"}

    # 7. JOIN WAGER COMMAND: "JOIN BET-A1B2C3D4 bc1q..."
    join_match = re.match(r"^JOIN\s+(BET-[A-F0-9]{8})\s+(\S+)$", clean_message, re.IGNORECASE)
    if join_match:
        bet_id = join_match.group(1).upper()
        payout_address = join_match.group(2)

        if not is_valid_btc_address(payout_address):
            reply = "That doesn't look like a valid BTC address."
            await send_sms_reply(payload.sender, reply)
            return {"status": "error", "action": "join_bet"}

        async with aiosqlite.connect(DB_FILE) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM bets WHERE bet_id = ?", (bet_id,)) as cursor:
                bet = await cursor.fetchone()

            if not bet:
                reply = f"Wager {bet_id} not found."
            elif bet["status"] != "PENDING_ACCEPTANCE":
                reply = f"Wager {bet_id} is no longer open for acceptance."
            elif bet["creator_token"] == anonymous_token:
                reply = "You cannot join your own wager."
            else:
                await db.execute("UPDATE bets SET opponent_token = ?, status = 'ACTIVE' WHERE bet_id = ?", (anonymous_token, bet_id))
                await db.execute("INSERT INTO bet_participants (bet_id, user_token, role, payout_wallet_address) VALUES (?, ?, 'OPPONENT', ?)", (bet_id, anonymous_token, payout_address))
                await db.commit()
                reply = f"Joined {bet_id}! Send {bet['wager_amount_sats']:,} sats to escrow: {bet['escrow_address']}"

        await send_sms_reply(payload.sender, reply)
        return {"status": "success", "action": "join_bet", "bet_id": bet_id}

    # 8. VOTE COMMAND: "VOTE BET-A1B2C3D4 <winner_token>"
    vote_match = re.match(r"^VOTE\s+(BET-[A-F0-9]{8})\s+(\S+)$", clean_message, re.IGNORECASE)
    if vote_match:
        bet_id = vote_match.group(1).upper()
        voted_winner_token = vote_match.group(2)

        async with aiosqlite.connect(DB_FILE) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM bets WHERE bet_id = ?", (bet_id,)) as cursor:
                bet = await cursor.fetchone()

            if not bet:
                reply = f"Wager {bet_id} not found."
            elif bet["status"] == "DISPUTED":
                reply = f"{bet_id} is disputed; ask a community validator to APPROVE it instead."
            elif anonymous_token not in (bet["creator_token"], bet["opponent_token"]):
                reply = "You're not a participant in this wager."
            else:
                col = "creator_vote" if anonymous_token == bet["creator_token"] else "opponent_vote"
                await db.execute(f"UPDATE bets SET {col} = ? WHERE bet_id = ?", (voted_winner_token, bet_id))

                async with db.execute("SELECT creator_vote, opponent_vote FROM bets WHERE bet_id = ?", (bet_id,)) as cursor:
                    updated = await cursor.fetchone()

                if updated["creator_vote"] and updated["opponent_vote"]:
                    if updated["creator_vote"] == updated["opponent_vote"]:
                        await db.execute(
                            "UPDATE bets SET winner_token = ?, status = 'RESOLVED', resolved_at = CURRENT_TIMESTAMP WHERE bet_id = ?",
                            (updated["creator_vote"], bet_id)
                        )
                        reply = f"Consensus reached on {bet_id}! Wager resolved."
                    else:
                        await db.execute("UPDATE bets SET status = 'DISPUTED' WHERE bet_id = ?", (bet_id,))
                        reply = f"Votes on {bet_id} conflict. Flagged DISPUTED for community approval."
                else:
                    reply = f"Vote recorded for {bet_id}. Waiting on the other participant."

                await db.commit()

        await send_sms_reply(payload.sender, reply)
        return {"status": "success", "action": "vote_bet", "bet_id": bet_id}

    # 9. APPROVE COMMAND (community validators, disputed bets only):
    # "APPROVE BET-A1B2C3D4 <winner_token>"
    approve_match = re.match(r"^APPROVE\s+(BET-[A-F0-9]{8})\s+(\S+)$", clean_message, re.IGNORECASE)
    if approve_match:
        bet_id = approve_match.group(1).upper()
        approved_winner_token = approve_match.group(2)

        async with aiosqlite.connect(DB_FILE) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM bets WHERE bet_id = ?", (bet_id,)) as cursor:
                bet = await cursor.fetchone()

            if not bet:
                reply = f"Wager {bet_id} not found."
            elif bet["status"] != "DISPUTED":
                reply = f"{bet_id} isn't disputed; nothing to approve."
            else:
                try:
                    await db.execute(
                        "INSERT INTO bet_approvals (bet_id, validator_token, approved_winner_token) VALUES (?, ?, ?)",
                        (bet_id, anonymous_token, approved_winner_token)
                    )
                except aiosqlite.IntegrityError:
                    reply = "You've already voted on this dispute."
                    await send_sms_reply(payload.sender, reply)
                    return {"status": "error", "action": "approve_bet"}

                new_count = bet["approvals_count"] + 1
                if new_count >= REQUIRED_COMMUNITY_APPROVALS:
                    await db.execute(
                        "UPDATE bets SET approvals_count = ?, winner_token = ?, status = 'RESOLVED', resolved_at = CURRENT_TIMESTAMP WHERE bet_id = ?",
                        (new_count, approved_winner_token, bet_id)
                    )
                    reply = f"Quorum reached on {bet_id}! Resolved."
                else:
                    await db.execute("UPDATE bets SET approvals_count = ? WHERE bet_id = ?", (new_count, bet_id))

# ==========================================
# ==========================================
import httpx

# ==========================================
# ==========================================
import httpx

async def send_sms_reply(recipient_phone: str, text: str):
    """The single source of truth for routing outbound messages"""
    if str(recipient_phone).startswith("tg_"):
        telegram_chat_id = recipient_phone.replace("tg_", "")
        token = "8881701685:AAEmoCt9YDdT8XGsoG4qEVei_RGHbNm4Eu4"
        telegram_api_url = f"https://telegram.org{token}/sendMessage"
        
        payload = {"chat_id": telegram_chat_id, "text": text}
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(telegram_api_url, json=payload, timeout=10.0)
                if response.status_code == 200:
                    print(f"[TELEGRAM SUCCESS] Sent message to {telegram_chat_id}")
                    return {"status": "telegram_sent"}
                else:
                    print(f"[TELEGRAM ERROR] {response.status_code}: {response.text}")
            except Exception as e:
                print(f"[TELEGRAM CRITICAL] Failed to contact API: {e}")
        return {"status": "telegram_failed"}
    else:
        print(f"[SMS OUTBOUND DELEGATE -> {recipient_phone}]: {text}")
        return {"status": "mock_sent"}

# ==========================================
# ==========================================
import httpx

async def send_sms_reply(recipient_phone: str, text: str):
    if str(recipient_phone).startswith("tg_"):
        telegram_chat_id = recipient_phone.replace("tg_", "")
        p1 = "8881701685"
        p2 = "AAEmoCt9YDdT8XGsoG4qEVei_RGHbNm4Eu4"
        url = "https://telegram.org" + p1 + ":" + p2 + "/sendMessage"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json={"chat_id": telegram_chat_id, "text": text}, timeout=10.0)
                if response.status_code == 200:
                    print(f"[TELEGRAM SUCCESS] Sent to {telegram_chat_id}")
                    return {"status": "telegram_sent"}
                print(f"[TELEGRAM ERROR] {response.status_code}: {response.text}")
            except Exception as e:
                print(f"[TELEGRAM CRITICAL] Failed: {e}")
        return {"status": "telegram_failed"}
    else:
        print(f"[SMS OUTBOUND DELEGATE -> {recipient_phone}]: {text}")
        return {"status": "mock_sent"}

# ==========================================
# 🔐 TELEGRAM MINI APP SECURITY VERIFIER
# ==========================================
import hmac
import hashlib
import urllib.parse

def verify_telegram_webapp_data(init_data: str) -> bool:
    """Validates that incoming bet payloads genuinely came from Telegram"""
    try:
        parsed_data = dict(urllib.parse.parse_qsl(init_data))
        received_hash = parsed_data.pop('hash', None)
        if not received_hash:
            return False
            
        data_check_string = "\n".join([f"{k}={v}" for k, v in sorted(parsed_data.items())])
        
        # Re-create signature using your token segments
        token = "8881701685:AAEmoCt9YDdT8XGsoG4qEVei_RGHbNm4Eu4"
        secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        
        return hmac.compare_digest(expected_hash, received_hash)
    except Exception:
        return False

# ==========================================
# 🤖 CUSTOMERPOTATOBOT NON-BLOCKING ROUTER
# ==========================================
import httpx
import asyncio

async def fire_and_forget_telegram(url, chat_id, text):
    """Executes outbound Telegram calls completely out-of-band"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json={"chat_id": chat_id, "text": text}, timeout=8.0)
            if response.status_code == 200:
                print(f"[TELEGRAM SUCCESS] Async sent to {chat_id}")
            else:
                print(f"[TELEGRAM ERROR] {response.status_code}: {response.text}")
        except Exception as e:
            print(f"[TELEGRAM CRITICAL] Background connection failed: {e}")

async def send_sms_reply(recipient_phone: str, text: str):
    if str(recipient_phone).startswith("tg_"):
        telegram_chat_id = recipient_phone.replace("tg_", "")
        p1 = "8881701685"
        p2 = "AAEmoCt9YDdT8XGsoG4qEVei_RGHbNm4Eu4"
        url = "https://telegram.org" + p1 + ":" + p2 + "/sendMessage"
        
        # Fire off the HTTP task in the background without awaiting it
        asyncio.create_task(fire_and_forget_telegram(url, telegram_chat_id, text))
        return {"status": "telegram_queued"}
    else:
        # Fallback to your original local Android gateway log print format
        print(f"[SMS OUTBOUND DELEGATE -> {recipient_phone}]: {text}")
        return {"status": "mock_sent"}
