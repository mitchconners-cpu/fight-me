#!/bin/bash
set -e

echo "=== 1. Locating sms_app2 directory ==="
SMS_DIR=$(find ~ -maxdepth 5 -type d -name "sms_app2" 2>/dev/null | head -n 1)

if [ -z "$SMS_DIR" ]; then
    echo "Error: Could not locate 'sms_app2' directory. Using current directory."
    SMS_DIR="."
else
    echo "Found sms_app2 at: $SMS_DIR"
    cd "$SMS_DIR"
fi

echo "=== 2. Activating Virtual Environment ==="
if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "No existing venv found in $SMS_DIR. Creating .venv..."
    python3.11 -m venv .venv
    source .venv/bin/activate
fi

echo "Active Python: $(which python)"

echo "=== 3. Installing Dependencies ==="
python -m pip install --upgrade pip
python -m pip install fastapi "uvicorn[standard]" sqlalchemy apscheduler pydantic

echo "=== 4. Writing Source Files with PyDoc Documentation ==="

cat << 'PYEOF' > database.py
"""
Database configuration module.

Establishes the SQLAlchemy engine, session maker, and base declarative class
for SQLite database connections.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

SQLALCHEMY_DATABASE_URL = "sqlite:///./wager_app.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """
    FastAPI dependency that provides a transactional database session per request.

    Yields:
        Session: SQLAlchemy database session.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
PYEOF

cat << 'PYEOF' > models.py
"""
Data models module.

Defines the database schema and enums for managing wager escrows and lifecycle states.
"""

from datetime import datetime
import enum
from sqlalchemy import Column, String, Integer, DateTime, Enum
from database import Base


class EscrowStatus(str, enum.Enum):
    """Enumeration representing all possible states of a wager escrow."""
    PENDING_DEPOSIT = "PENDING_DEPOSIT"
    FUNDS_LOCKED = "FUNDS_LOCKED"
    DISPUTED = "DISPUTED"
    RELEASED = "RELEASED"
    REFUNDED = "REFUNDED"


class WagerEscrow(Base):
    """
    SQLAlchemy model representing a wager's escrow state and ledger balances.

    Attributes:
        id (str): Unique primary key identifier for the escrow instance.
        wager_id (str): Identifier for the associated wager.
        creator_id (str): Identifier or wallet tag for the wager creator.
        opponent_id (str): Identifier or wallet tag for the wager opponent.
        amount_sats (int): Required deposit amount per player in Satoshi.
        escrow_address (str): Isolated deposit address derived for this escrow.
        status (EscrowStatus): Current status in the escrow state machine.
        creator_deposited (int): Amount of Satoshi deposited by the creator.
        opponent_deposited (int): Amount of Satoshi deposited by the opponent.
        created_at (datetime): Timestamp when the escrow was created.
        expires_at (datetime): Cutoff timestamp after which the escrow expires.
    """
    __tablename__ = "wager_escrows"

    id = Column(String, primary_key=True, index=True)
    wager_id = Column(String, nullable=False, index=True)
    creator_id = Column(String, nullable=False)
    opponent_id = Column(String, nullable=True)

    amount_sats = Column(Integer, nullable=False)
    escrow_address = Column(String, unique=True, nullable=False, index=True)
    status = Column(Enum(EscrowStatus), default=EscrowStatus.PENDING_DEPOSIT, nullable=False)

    creator_deposited = Column(Integer, default=0, nullable=False)
    opponent_deposited = Column(Integer, default=0, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
PYEOF

cat << 'PYEOF' > background_tasks.py
"""
Background task worker module.

Contains job functions managed by APScheduler to process expired escrows
and execute automated refunds.
"""

import logging
from datetime import datetime
from sqlalchemy.orm import Session
from database import SessionLocal
from models import WagerEscrow, EscrowStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def process_expired_escrows():
    """
    Scans the database for pending escrows past their expiration threshold.

    Identifies escrows in PENDING_DEPOSIT status where expires_at <= current UTC time,
    triggers refunds for any partial deposits made by participants, and transitions
    the state to REFUNDED.
    """
    db: Session = SessionLocal()
    try:
        now = datetime.utcnow()
        expired_escrows = db.query(WagerEscrow).filter(
            WagerEscrow.expires_at <= now,
            WagerEscrow.status == EscrowStatus.PENDING_DEPOSIT
        ).all()

        for escrow in expired_escrows:
            logger.info("Processing expired escrow: %s (Wager ID: %s)", escrow.id, escrow.wager_id)

            if escrow.creator_deposited > 0:
                logger.info(
                    "Refunding %d sats to Creator %s",
                    escrow.creator_deposited,
                    escrow.creator_id
                )

            if escrow.opponent_deposited > 0:
                logger.info(
                    "Refunding %d sats to Opponent %s",
                    escrow.opponent_deposited,
                    escrow.opponent_id
                )

            escrow.status = EscrowStatus.REFUNDED
            db.commit()

    except Exception as exc:
        logger.error("Error encountered processing expired escrows: %s", exc)
        db.rollback()
    finally:
        db.close()
PYEOF

cat << 'PYEOF' > gateway_app.py
"""
Main FastAPI web application.

Exposes webhook endpoints for processing deposit confirmations and manages
the APScheduler background worker lifecycle.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import secrets
from fastapi import FastAPI, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler

from database import engine, get_db, Base
from models import WagerEscrow, EscrowStatus
from background_tasks import process_expired_escrows

Base.metadata.create_all(bind=engine)

scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages application startup and shutdown lifecycle events.

    Starts APScheduler on app initialization and shuts it down on exit.
    """
    scheduler.add_job(
        process_expired_escrows,
        trigger="interval",
        seconds=60,
        id="expired_escrow_checker",
        replace_existing=True
    )
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(
    title="Wager Escrow Gateway API",
    description="API for managing wager escrow balances and deposit webhooks.",
    version="1.0.0",
    lifespan=lifespan
)


class CreateEscrowRequest(BaseModel):
    """Request payload for initializing a new escrow account."""
    wager_id: str
    creator_id: str
    opponent_id: str | None = None
    amount_sats: int
    ttl_minutes: int = 30


class DepositWebhookPayload(BaseModel):
    """Request payload received from blockchain indexers or node webhooks."""
    escrow_address: str
    txid: str
    amount_received_sats: int
    sender_id: str


@app.post("/api/v1/escrow/create", status_code=status.HTTP_201_CREATED)
def create_escrow(payload: CreateEscrowRequest, db: Session = Depends(get_db)):
    """
    Initializes a new escrow record with an assigned dynamic address.

    Args:
        payload (CreateEscrowRequest): Details required to instantiate the escrow.
        db (Session): Database dependency session.

    Returns:
        dict: The created escrow record details.
    """
    escrow_id = f"escrow_{secrets.token_hex(6)}"
    derived_address = f"bc1q_escrow_{secrets.token_hex(8)}"
    expiration = datetime.utcnow() + timedelta(minutes=payload.ttl_minutes)

    escrow = WagerEscrow(
        id=escrow_id,
        wager_id=payload.wager_id,
        creator_id=payload.creator_id,
        opponent_id=payload.opponent_id,
        amount_sats=payload.amount_sats,
        escrow_address=derived_address,
        expires_at=expiration
    )

    db.add(escrow)
    db.commit()
    db.refresh(escrow)
    return escrow


@app.post("/api/v1/escrow/deposit-webhook")
def handle_deposit_webhook(payload: DepositWebhookPayload, db: Session = Depends(get_db)):
    """
    Receives incoming deposit notifications and updates escrow ledger balances.

    Args:
        payload (DepositWebhookPayload): Deposit details including address and satoshis.
        db (Session): Database dependency session.

    Returns:
        dict: Success status and updated escrow state.
    """
    escrow = db.query(WagerEscrow).filter(
        WagerEscrow.escrow_address == payload.escrow_address
    ).first()

    if not escrow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Escrow address not found."
        )

    if escrow.status != EscrowStatus.PENDING_DEPOSIT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Escrow is locked or closed. Current status: {escrow.status}"
        )

    if payload.sender_id == escrow.creator_id:
        escrow.creator_deposited += payload.amount_received_sats
    elif payload.sender_id == escrow.opponent_id:
        escrow.opponent_deposited += payload.amount_received_sats
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sender ID does not match any assigned wager participant."
        )

    required_total = escrow.amount_sats * 2
    if (escrow.creator_deposited + escrow.opponent_deposited) >= required_total:
        escrow.status = EscrowStatus.FUNDS_LOCKED

    db.commit()
    db.refresh(escrow)
    return {"status": "success", "escrow_status": escrow.status, "escrow_id": escrow.id}
PYEOF

echo "=== 5. Launching Uvicorn Server ==="
python -m uvicorn gateway_app:app --reload
