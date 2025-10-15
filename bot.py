import logging
import asyncio
import uvicorn
from fastapi import FastAPI
from pyrogram import Client
from config import BOT, API, OWNER


logging.getLogger().setLevel(logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.ERROR)

app = FastAPI()

@app.get('/')
async def home():
    return {"status": "running", "message": "MnBot is running!"}

@app.get('/health')
async def health_check():
    return {"status": "healthy"}


class MN_Bot(Client):
    def __init__(self):
        super().__init__(
            "MN-Bot",
            api_id=API.ID,
            api_hash=API.HASH,
            bot_token=BOT.TOKEN,
            plugins=dict(root="plugins"),
            workers=16,
        )

    async def start(self):
        await super().start()
        me = await self.get_me()
        BOT.USERNAME = f"@{me.username}"
        self.mention = me.mention
        self.username = me.username
        await self.send_message(
            chat_id=OWNER.ID,
            text=f"{me.first_name} ✅✅ BOT started successfully ✅✅"
        )
        logging.info(f"✅ {me.first_name} BOT started successfully")

    async def stop(self, *args):
        await super().stop()
        logging.info("Bot Stopped 🙄")


async def main():
    """Main function to run both FastAPI and Pyrogram bot in the same event loop"""
    
    # Initialize bot
    bot = MN_Bot()
    
    # Configure uvicorn server
    config = uvicorn.Config(
        app,
        host='0.0.0.0',
        port=8000,
        loop="asyncio",
        log_level="info"
    )
    server = uvicorn.Server(config)
    
    # Run both bot and FastAPI server concurrently
    async with bot:
        await bot.start()
        
        # Create server task
        api_task = asyncio.create_task(server.serve())
        
        # Keep the event loop running
        try:
            await asyncio.Event().wait()
        except (KeyboardInterrupt, SystemExit):
            logging.info("Received stop signal")
        finally:
            await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
