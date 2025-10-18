import logging
import asyncio
import uvicorn
import os
from fastapi import FastAPI, Request, HTTPException
from pyrogram import Client
from pyrogram.errors import FloodWait, PeerIdInvalid
from config import BOT, API, OWNER

# =============================
# Logging Configuration
# =============================
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)

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
    return {
        "status": "healthy",
        "bot_ready": bot_ready.is_set()
    }

# =============================
# Webhook Endpoint
# =============================
@app.post("/webhook/{bot_token}")
async def webhook_handler(bot_token: str, request: Request):
    """Handle incoming Telegram webhook updates"""
    
    # Validate token
    if bot_token != BOT.TOKEN:
        raise HTTPException(status_code=404, detail="Not found")
    
    # Wait for bot to be ready
    try:
        await asyncio.wait_for(bot_ready.wait(), timeout=10.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=503, detail="Bot initializing")
    
    if not bot_instance:
        raise HTTPException(status_code=503, detail="Bot not available")
    
    try:
        update = await request.json()
        update_id = update.get("update_id")
        
        # Prevent duplicates
        if update_id and update_id in processed_updates:
            return {"ok": True}
        
        if update_id:
            processed_updates.add(update_id)
            
            # Cleanup cache
            if len(processed_updates) > MAX_UPDATE_CACHE:
                processed_updates.clear()
        
        # Process update
        asyncio.create_task(process_update(update))
        
        return {"ok": True}
    
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return {"ok": True}


async def process_update(update: dict):
    """Process Telegram updates using Pyrogram's get_messages"""
    try:
        # Handle messages
        if "message" in update:
            msg_data = update["message"]
            chat_id = msg_data.get("chat", {}).get("id")
            message_id = msg_data.get("message_id")
            
            if not chat_id or not message_id:
                return
            
            try:
                # Fetch message (resolves peer automatically)
                message = await bot_instance.get_messages(chat_id, message_id)
                
                # Pass through Pyrogram handlers (your plugins)
                for group in sorted(bot_instance.dispatcher.groups.keys()):
                    handlers = bot_instance.dispatcher.groups[group]
                    
                    for handler in handlers:
                        try:
                            if await handler.check(bot_instance, message):
                                await handler.callback(bot_instance, message)
                                break
                        except Exception as e:
                            logger.error(f"Handler error: {e}", exc_info=True)
            
            except PeerIdInvalid:
                logger.warning(f"PeerIdInvalid for chat {chat_id}")
            except Exception as e:
                logger.error(f"Message error: {e}", exc_info=True)
        
        # Handle edited messages
        elif "edited_message" in update:
            msg_data = update["edited_message"]
            chat_id = msg_data.get("chat", {}).get("id")
            message_id = msg_data.get("message_id")
            
            if not chat_id or not message_id:
                return
            
            try:
                message = await bot_instance.get_messages(chat_id, message_id)
                
                for group in sorted(bot_instance.dispatcher.groups.keys()):
                    handlers = bot_instance.dispatcher.groups[group]
                    
                    for handler in handlers:
                        try:
                            if await handler.check(bot_instance, message):
                                await handler.callback(bot_instance, message)
                                break
                        except Exception as e:
                            logger.error(f"Handler error: {e}", exc_info=True)
            
            except PeerIdInvalid:
                logger.warning(f"PeerIdInvalid for edited message")
            except Exception as e:
                logger.error(f"Edited message error: {e}", exc_info=True)
    
    except Exception as e:
        logger.error(f"Update processing error: {e}", exc_info=True)


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
            plugins=dict(root="plugins"),
            workers=16,
            workdir="/tmp",  # Use /tmp for Docker compatibility
            no_updates=True  # Disable polling (we use webhooks)
        )

    async def start(self):
        await super().start()
        me = await self.get_me()
        BOT.USERNAME = f"@{me.username}"
        self.mention = me.mention
        self.username = me.username

        # Send startup notification
        try:
            await self.resolve_peer(OWNER.ID)
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
        except PeerIdInvalid:
            logger.warning(f"Owner {OWNER.ID} not in session. Send /start to bot first.")
        except Exception as e:
            logger.warning(f"Could not notify owner: {e}")

        logging.info(f"✅ {me.first_name} BOT started successfully")

    async def stop(self, *args):
        await super().stop()
        logging.info("🚫 Bot Stopped")


# =============================
# Webhook Setup
# =============================
async def setup_webhook(webhook_url: str):
    """Configure Telegram webhook"""
    try:
        import httpx
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Delete old webhook
            await client.post(
                f"https://api.telegram.org/bot{BOT.TOKEN}/deleteWebhook",
                json={"drop_pending_updates": True}
            )
            logger.info("Old webhook deleted")
            
            await asyncio.sleep(2)
            
            # Set new webhook
            response = await client.post(
                f"https://api.telegram.org/bot{BOT.TOKEN}/setWebhook",
                json={
                    "url": webhook_url,
                    "allowed_updates": ["message", "edited_message"],
                    "drop_pending_updates": True,
                    "max_connections": 40
                }
            )
            
            result = response.json()
            if result.get("ok"):
                logger.info(f"✅ Webhook set: {webhook_url}")
                return True
            else:
                logger.error(f"❌ Webhook failed: {result}")
                return False
    
    except Exception as e:
        logger.error(f"Webhook setup error: {e}", exc_info=True)
        return False


# =============================
# FastAPI Lifecycle
# =============================
@app.on_event("startup")
async def startup_event():
    """Initialize bot when FastAPI starts"""
    global bot_instance
    
    logger.info("🚀 Starting bot...")
    
    try:
        WEBHOOK_URL = os.getenv("WEBHOOK_URL")
        if not WEBHOOK_URL:
            logger.error("❌ WEBHOOK_URL not set!")
            return
        
        # Create temp directory for session
        os.makedirs("/tmp", exist_ok=True)
        
        # Initialize bot
        bot_instance = MN_Bot()
        await bot_instance.start()
        
        # Setup webhook
        await setup_webhook(WEBHOOK_URL)
        
        # Mark ready
        bot_ready.set()
        logger.info("✅ Bot fully ready!")
    
    except Exception as e:
        logger.error(f"❌ Startup failed: {e}", exc_info=True)


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    global bot_instance
    
    if bot_instance:
        try:
            await bot_instance.stop()
        except Exception as e:
            logger.error(f"Shutdown error: {e}")


# =============================
# Main Entry Point
# =============================
if __name__ == "__main__":
    PORT = int(os.getenv("PORT", 8000))
    
    logger.info(f"🚀 Starting server on port {PORT}...")
    
    uvicorn.run(
        "bot:app",
        host="0.0.0.0",
        port=PORT,
        log_level="info",
        access_log=True,
        loop="asyncio"
    )
