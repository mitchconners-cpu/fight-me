import os
import asyncio
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

load_dotenv()

async def start_web(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Potato Bot online!")

async def start_mobile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Mobile Smash Bot online!")

async def main():
    web_app = ApplicationBuilder().token(os.getenv("WEB_BOT_TOKEN")).build()
    web_app.add_handler(CommandHandler("start", start_web))

    mobile_app = ApplicationBuilder().token(os.getenv("MOBILE_BOT_TOKEN")).build()
    mobile_app.add_handler(CommandHandler("start", start_mobile))

    await web_app.initialize()
    await mobile_app.initialize()
    await web_app.start()
    await mobile_app.start()

    await asyncio.gather(
        web_app.updater.start_polling(),
        mobile_app.updater.start_polling()
    )

if __name__ == "__main__":
    asyncio.run(main())
