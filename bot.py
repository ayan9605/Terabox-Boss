import logging
import asyncio
import os
from fastapi import FastAPI, Request, HTTPException
from pyrogram import Client
from pyrogram.errors import FloodWait, PeerIdInvalid, BadRequest
from config import BOT, API, OWNER

# =============================
# Logging Configuration
# =============================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logging.getLogger("pyrogram").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)

# =============================
# FastAPI Setup
# =============================
app = FastAPI()

# Global variables
bot_instance = None
bot_ready = asyncio.Event()
processed_updates = set()
MAX_UPDATE_CACHE = 1000

# =============================
# API Endpoints
# =============================
@app.get("/")
async def root():
    return {
        "status": "running",
        "message": "MN TeraBox Bot is active",
        "mode": "webhook",
        "bot_ready": bot_ready.is_set()
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "bot_ready": bot_ready.is_set(),
        "bot_active": bot_instance is not None
    }

@app.head("/")
async def head_root():
    """Handle HEAD requests for health checks"""
    return {"status": "ok"}

# =============================
# Webhook Endpoint
# =============================
@app.post("/webhook/{bot_token}")
async def webhook_handler(bot_token: str, request: Request):
    """Handle Telegram webhook updates"""
    
    if bot_token != BOT.TOKEN:
        logger.warning(f"Invalid token attempt")
        raise HTTPException(status_code=404, detail="Not found")
    
    try:
        await asyncio.wait_for(bot_ready.wait(), timeout=10.0)
    except asyncio.TimeoutError:
        logger.error("Bot not ready - timeout")
        raise HTTPException(status_code=503, detail="Bot initializing")
    
    if not bot_instance:
        raise HTTPException(status_code=503, detail="Bot not available")
    
    try:
        update = await request.json()
        update_id = update.get("update_id")
        
        if update_id and update_id in processed_updates:
            return {"ok": True}
        
        if update_id:
            processed_updates.add(update_id)
            
            if len(processed_updates) > MAX_UPDATE_CACHE:
                processed_updates.clear()
                logger.info("Update cache cleared")
        
        asyncio.create_task(process_update(update))
        
        return {"ok": True}
        
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return {"ok": True}

# =============================
# Update Processor
# =============================
async def process_update(update: dict):
    """Process Telegram updates"""
    try:
        if "message" in update:
            msg_data = update["message"]
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
                logger.warning(f"PeerIdInvalid for chat {chat_id}")
            except BadRequest as e:
                logger.warning(f"BadRequest: {e}")
            except Exception as e:
                logger.error(f"Message processing error: {e}", exc_info=True)
        
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
                            
            except Exception as e:
                logger.error(f"Edited message error: {e}", exc_info=True)
                
    except Exception as e:
        logger.error(f"Update processing error: {e}", exc_info=True)

# =============================
# Telegram Bot Class
# =============================
class MN_Bot(Client):
    def __init__(self):
        # ✅ CRITICAL FIX: Remove existing session before init
        session_file = "/tmp/MN-Bot.session"
        if os.path.exists(session_file):
            try:
                os.remove(session_file)
                logger.info("🗑️ Removed old session")
            except:
                pass
        
        super().__init__(
            name="MN-Bot",
            api_id=API.ID,
            api_hash=API.HASH,
            bot_token=BOT.TOKEN,  # ✅ This should work for bots
            plugins=dict(root="plugins"),
            workers=16,
            workdir="/tmp",
            no_updates=True,
            in_memory=False  # ✅ Use file storage, not in-memory
        )

    async def start(self):
        """Start bot"""
        await super().start()
        me = await self.get_me()
        BOT.USERNAME = f"@{me.username}"
        self.mention = me.mention
        self.username = me.username

        logger.info(f"✅ {me.first_name} BOT started successfully")

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
        except PeerIdInvalid:
            logger.warning(f"Owner {OWNER.ID} not found - needs to /start bot first")
        except Exception as e:
            logger.warning(f"Could not notify owner: {e}")

    async def stop(self, *args):
        """Stop bot"""
        await super().stop()
        logger.info("🛑 Bot Stopped")

# =============================
# Webhook Setup
# =============================
async def setup_webhook(webhook_url: str):
    """Configure Telegram webhook"""
    try:
        import httpx
        
        logger.info("🔗 Setting up webhook...")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.post(
                f"https://api.telegram.org/bot{BOT.TOKEN}/deleteWebhook",
                json={"drop_pending_updates": True}
            )
            logger.info("Old webhook deleted")
            
            await asyncio.sleep(2)
            
            response = await client.post(
                f"https://api.telegram.org/bot{BOT.TOKEN}/setWebhook",
                json={
                    "url": webhook_url,
                    "allowed_updates": ["message", "edited_message", "callback_query"],
                    "drop_pending_updates": True,
                    "max_connections": 40
                }
            )
            
            result = response.json()
            if result.get("ok"):
                logger.info(f"✅ Webhook set: {webhook_url}")
                
                info = await client.get(
                    f"https://api.telegram.org/bot{BOT.TOKEN}/getWebhookInfo"
                )
                logger.info(f"📡 Webhook info: {info.json()}")
                return True
            else:
                logger.error(f"❌ Webhook failed: {result}")
                return False
                
    except Exception as e:
        logger.error(f"Webhook setup error: {e}", exc_info=True)
        return False

# =============================
# Startup/Shutdown
# =============================
@app.on_event("startup")
async def startup_event():
    """Initialize on startup"""
    global bot_instance
    
    logger.info("=" * 60)
    logger.info("🚀 Starting MN TeraBox Bot...")
    logger.info("=" * 60)
    
    try:
        WEBHOOK_URL = os.getenv("WEBHOOK_URL")
        if not WEBHOOK_URL:
            logger.error("❌ WEBHOOK_URL not set!")
            logger.error("Set: https://your-app.onrender.com/webhook/YOUR_BOT_TOKEN")
            return
        
        logger.info(f"Webhook URL: {WEBHOOK_URL}")
        
        # Ensure /tmp exists
        os.makedirs("/tmp", exist_ok=True)
        
        logger.info("Initializing bot...")
        bot_instance = MN_Bot()
        
        logger.info("Starting bot...")
        await bot_instance.start()
        
        logger.info("Configuring webhook...")
        webhook_ok = await setup_webhook(WEBHOOK_URL)
        
        if webhook_ok:
            bot_ready.set()
            logger.info("=" * 60)
            logger.info("✅ Bot fully ready!")
            logger.info(f"📡 Listening at: {WEBHOOK_URL}")
            logger.info("=" * 60)
        else:
            logger.error("❌ Webhook setup failed!")
            
    except Exception as e:
        logger.error(f"❌ Startup failed: {e}", exc_info=True)

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    global bot_instance
    
    logger.info("=" * 60)
    logger.info("🛑 Shutting down...")
    logger.info("=" * 60)
    
    if bot_instance:
        try:
            await bot_instance.stop()
            logger.info("✅ Bot stopped gracefully")
        except Exception as e:
            logger.error(f"Error stopping bot: {e}")
    
    logger.info("👋 Goodbye!")

# =============================
# Entry Point
# =============================
if __name__ == "__main__":
    import uvicorn
    
    PORT = int(os.getenv("PORT", 8000))
    
    logger.info("=" * 60)
    logger.info(f"🌐 Starting server on port {PORT}...")
    logger.info("=" * 60)
    
    uvicorn.run(
        "bot:app",
        host="0.0.0.0",
        port=PORT,
        log_level="info",
        access_log=True,
        loop="asyncio"
    )
