import time
import requests
from gateway_app import app
import asyncio

BOT_TOKEN = "8881701685:AAFLtJ-owkpoCUpitpLw2vDmaxFR2Xe9-SA"
URL = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
offset = 0

print("🚀 Polling listener active. Send a message in Telegram...")

while True:
    try:
        res = requests.get(f"{URL}?offset={offset}&timeout=5").json()
        if res.get("ok") and res.get("result"):
            for update in res["result"]:
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                chat_id = msg.get("chat", {}).get("id")
                text = msg.get("text", "")
                print(f"Received from {chat_id}: {text}")
                
                # Forward to gateway_app logic directly
                from gateway_app import send_telegram_message
                if text in ["5", "Option 5", "/help", "start/ HELP"]:
                    send_telegram_message(chat_id, "📋 **Full Command List**\n\n1. View Menu\n2. Check Balance\n3. Place Bet\n4. Active Bets\n5. Full Command List")
                elif text in ["start/", "/start"]:
                    send_telegram_message(chat_id, "Welcome to CustomerPotatoBot! Select an option from 1-5.")
                else:
                    send_telegram_message(chat_id, f"Received: {text}\nType '5' for command list.")
        time.sleep(1)
    except Exception as e:
        print(f"Error: {e}")
        time.sleep(2)
