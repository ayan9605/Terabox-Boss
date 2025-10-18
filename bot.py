import logging
import asyncio
import uvicorn
from fastapi import FastAPI
from pyrogram import Client
from pyrogram.errors import FloodWait
from config import BOT, API, OWNER

# =============================
# Logging Configuration
# =============================
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.ERROR)

# =============================
# FastAPI Setup
# =============================
app = FastAPI()

@app.get("/")
async def root():
    return {"status": "running", "message": "MnBot is running!"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

# =============================
# Telegram Bot Class
# =============================
class MN_Bot(Client):
    def __init__(self):
        super().__init__(
            "MN-Bot",
            api_id=API.ID,
            api_hash=API.HASH,
            bot_token=BOT.TOKEN,
            plugins=dict(root="plugins"),  # Auto-load all handlers
            workers=16,
        )

    async def start(self):
        await super().start()
        me = await self.get_me()
        BOT.USERNAME = f"@{me.username}"
        self.mention = me.mention
        self.username = me.username

        try:
            await self.send_message(
                chat_id=OWNER.ID,
                text=f"{me.first_name} ✅✅ BOT started successfully ✅✅"
            )
        except FloodWait as e:
            await asyncio.sleep(e.value)
            await self.send_message(
                chat_id=OWNER.ID,
                text=f"{me.first_name} ✅✅ BOT started successfully ✅✅"
            )

        logging.info(f"✅ {me.first_name} BOT started successfully")

    async def stop(self, *args):
        await super().stop()
        logging.info("🚫 Bot Stopped")


# =============================
# Main Runner
# =============================
async def main():
    bot = MN_Bot()

    # FastAPI server config
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=8000,
        loop="asyncio",
        log_level="info"
    )
    server = uvicorn.Server(config)

    # ✅ IMPORTANT: DON'T call bot.start() manually — async with handles it automatically
    async with bot:
        api_task = asyncio.create_task(server.serve())

        try:
            logging.info("🚀 BOT and FastAPI are now running...")
            await asyncio.Event().wait()
        except (KeyboardInterrupt, SystemExit):
            logging.info("⚠ Shutdown signal received...")
        finally:
            await bot.stop()


# =============================
# Entry Point
# =============================
if __name__ == "__main__":
    asyncio.run(main())
