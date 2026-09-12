import sqlite3
import logging
from telegram import Update
from telegram.ext import ContextTypes

DB_PATH = "project.db"

def get_bet_record(bet_id: str):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT bet_id, status, wager_amount_sats, escrow_address FROM bets WHERE bet_id = ?", (bet_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

async def check_bet_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not context.args:
        return
    bet_id = context.args[0].upper()
    bet = get_bet_record(bet_id)
    if not bet:
        await update.message.reply_text(f"❌ Wager `{bet_id}` not found.", parse_mode="Markdown")
        return

    await update.message.reply_text(
        f"📊 **Wager Status: `{bet['bet_id']}`**\n"
        f"• **State:** `{bet['status']}`\n"
        f"• **Amount:** {bet['wager_amount_sats']} sats\n"
        f"• **Escrow:** `{bet['escrow_address'] or 'N/A'}`",
        parse_mode="Markdown",
    )
