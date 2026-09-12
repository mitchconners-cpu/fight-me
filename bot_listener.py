"""
Telegram Bot Module for Escrow Notifications and User Engagement.

Handles incoming user interactions via Telegram commands and provides
asynchronous messaging utilities to alert users of escrow state updates.
"""

import logging
import random
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MESSAGES = [
    "Why do programmers prefer dark mode? Because light attracts bugs! 🐛 Welcome to the Escrow Bot!",
    "There are 10 types of people in the world: those who understand binary, and those who don't. Great to have you here!",
    "Remember: your code might have bugs, but your potential is feature-complete! Go step outside, catch some fresh air, and make today count! ☀️",
    "Why was the Bitcoin trader calm? Because they knew how to keep their cool under pressure! Welcome aboard!",
    "Life is short—go outside, touch some grass, grab a great cup of coffee, and let us handle your wager escrows! ☕🌲",
    "Don't worry if something doesn't work right away. If everything worked on the first try, software engineers would be out of a job! Welcome!"
]


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles the /start command when a user connects to the Telegram bot.

    Delivers a greeting along with a randomized pun or motivational message.
    """
    user_name = update.effective_user.first_name if update.effective_user else "Friend"
    selected_message = random.choice(MESSAGES)
    
    greeting = (
        f"Hey {user_name}! 👋\n\n"
        f"{selected_message}\n\n"
        "-----------------------------------\n"
        "⚡ **Escrow Commands:**\n"
        "• `/status <wager_id>` - Check your current wager status\n"
        "• `/help` - View usage guide"
    )
    
    await update.message.reply_text(greeting, parse_mode="Markdown")


async def send_escrow_notification(chat_id: str, message: str, bot_token: str = BOT_TOKEN) -> None:
    """
    Sends an automated status or refund alert to a specific Telegram user.

    Args:
        chat_id (str): The Telegram chat ID of the recipient.
        message (str): Text payload describing the escrow event.
        bot_token (str): Telegram Bot API authorization token.
    """
    from telegram import Bot
    bot = Bot(token=bot_token)
    try:
        await bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown")
        logger.info("Successfully sent notification to %s", chat_id)
    except Exception as err:
        logger.error("Failed to send Telegram notification to %s: %s", chat_id, err)


def run_bot() -> None:
    """Initializes and runs the Telegram bot polling loop."""
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    logger.info("Telegram Bot started. Listening for connections...")
    app.run_polling()


if __name__ == "__main__":
    run_bot()
