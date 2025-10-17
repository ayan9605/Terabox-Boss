import logging
import asyncio
import uvicorn
import os
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from pyrogram import Client
from pyrogram.errors import FloodWait
from config import BOT, API, OWNER
import json

# =============================
# Logging Configuration
# =============================
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.ERROR)

# =============================
# FastAPI Setup
# =============================
app = FastAPI()

# Global bot instance
bot_instance = None
bot_ready = asyncio.Event()
processed_updates = set()
MAX_UPDATE_CACHE = 1000

@app.get("/")
async def root():
    return {"status": "running", "message": "MnBot is running!"}

@app.get("/health")
async def health():
    return {"status": "healthy", "bot_ready": bot_ready.is_set()}

# =============================
# Webhook Endpoint - SIMPLIFIED
# =============================
@app.post(f"/webhook/{{bot_token}}")
async def webhook_handler(bot_token: str, request: Request, background_tasks: BackgroundTasks):
    """
    Telegram webhook endpoint - Simplified version
    """
    if bot_token != BOT.TOKEN:
        raise HTTPException(status_code=404)
    
    try:
        await asyncio.wait_for(bot_ready.wait(), timeout=10.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=503, detail="Bot not ready")
    
    if bot_instance is None:
        raise HTTPException(status_code=503, detail="Bot not initialized")
    
    try:
        # Get raw update data
        update_data = await request.json()
        update_id = update_data.get("update_id")
        
        # Check duplicate
        if update_id in processed_updates:
            return {"ok": True}
        
        processed_updates.add(update_id)
        
        if len(processed_updates) > MAX_UPDATE_CACHE:
            processed_updates.clear()
        
        # ✅ SIMPLE: Use Telegram Bot API directly to forward update
        # This bypasses Pyrogram's complex parsing
        background_tasks.add_task(handle_update_simple, update_data)
        
        return {"ok": True}
    
    except Exception as e:
        logging.error(f"Webhook error: {e}", exc_info=True)
        return {"ok": True}


async def handle_update_simple(update_data: dict):
    """
    ✅ SIMPLIFIED: Process updates using basic approach
    """
    try:
        # Handle messages
        if "message" in update_data:
            msg = update_data["message"]
            chat_id = msg.get("chat", {}).get("id")
            text = msg.get("text", "")
            
            # Import and run handlers manually
            if text:
                # This triggers your plugins
                # Pyrogram's dispatcher will handle it
                from pyrogram import types
                
                # Create message object
                message = types.Message(
                    id=msg.get("message_id"),
                    from_user=types.User(
                        id=msg.get("from", {}).get("id"),
                        is_self=False,
                        is_bot=msg.get("from", {}).get("is_bot", False),
                        first_name=msg.get("from", {}).get("first_name", ""),
                        last_name=msg.get("from", {}).get("last_name"),
                        username=msg.get("from", {}).get("username")
                    ) if "from" in msg else None,
                    date=msg.get("date"),
                    chat=types.Chat(
                        id=chat_id,
                        type=msg.get("chat", {}).get("type", "private"),
                        title=msg.get("chat", {}).get("title")
                    ),
                    text=text
                )
                
                # Dispatch to handlers
                for group in sorted(bot_instance.dispatcher.groups.keys()):
                    for handler in bot_instance.dispatcher.groups[group]:
                        try:
                            if await handler.check(bot_instance, message):
                                await handler.callback(bot_instance, message)
                                break
                        except Exception as e:
                            logging.error(f"Handler error: {e}", exc_info=True)
                            
    except Exception as e:
        logging.error(f"Error handling update: {e}", exc_info=True)


# =============================
# Telegram Bot Class
# =============================
class MN_Bot(Client):
    def __init__(self):
        super().__init__(
            name="MN-Bot",
            api_id=API.ID,
            api_hash=API.HASH,
            bot_token=BOT.TOKEN,
            plugins=dict(root="plugins"),
            workers=16,
            workdir="/tmp",
            no_updates=True  # ✅ Disable auto-polling for webhook mode
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
                text=f"✅ {me.first_name} BOT started"
            )
        except Exception as e:
            logging.warning(f"Startup message failed: {e}")

        logging.info(f"✅ {me.first_name} BOT ready")

    async def stop(self, *args):
        await super().stop()
        logging.info("🚫 Bot Stopped")


# =============================
# Webhook Setup
# =============================
async def setup_webhook(bot: MN_Bot, webhook_url: str):
    """Setup webhook"""
    try:
        import httpx
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Delete old
            await client.post(
                f"https://api.telegram.org/bot{BOT.TOKEN}/deleteWebhook",
                json={"drop_pending_updates": True}
            )
            
            await asyncio.sleep(2)
            
            # Set new
            response = await client.post(
                f"https://api.telegram.org/bot{BOT.TOKEN}/setWebhook",
                json={
                    "url": webhook_url,
                    "allowed_updates": ["message", "edited_message", "callback_query"],
                    "drop_pending_updates": True
                }
            )
            
            result = response.json()
            if result.get("ok"):
                logging.info(f"✅ Webhook set: {webhook_url}")
            else:
                logging.error(f"❌ Webhook failed: {result}")
                
    except Exception as e:
        logging.error(f"Webhook setup error: {e}", exc_info=True)


# =============================
# Startup
# =============================
@app.on_event("startup")
async def startup_event():
    global bot_instance
    
    logging.info("🚀 Initializing...")
    
    try:
        WEBHOOK_URL = os.getenv("WEBHOOK_URL")
        if not WEBHOOK_URL:
            logging.error("❌ WEBHOOK_URL not set!")
            return
        
        os.makedirs("/tmp", exist_ok=True)
        
        bot_instance = MN_Bot()
        await bot_instance.start()
        await setup_webhook(bot_instance, WEBHOOK_URL)
        
        bot_ready.set()
        logging.info("✅ Ready!")
        
    except Exception as e:
        logging.error(f"❌ Init failed: {e}", exc_info=True)


@app.on_event("shutdown")
async def shutdown_event():
    global bot_instance
    if bot_instance:
        try:
            await bot_instance.stop()
        except:
            pass


if __name__ == "__main__":
    PORT = int(os.getenv("PORT", 8000))
    uvicorn.run("bot:app", host="0.0.0.0", port=PORT, log_level="info")
