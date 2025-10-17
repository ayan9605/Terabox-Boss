import logging
import asyncio
import os
from fastapi import FastAPI, Request, HTTPException
from pyrogram import Client
from pyrogram.errors import FloodWait, PeerIdInvalid
from config import BOT, API, OWNER

# =============================
# Logging Configuration
# =============================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logging.getLogger("pyrogram").setLevel(logging.WARNING)
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
    return {"status": "running", "message": "MN TeraBox Bot"}

@app.get("/health")
async def health():
    return {
        "status": "healthy", 
        "bot_ready": bot_ready.is_set(),
        "bot_active": bot_instance is not None
    }

# =============================
# Webhook Endpoint
# =============================
@app.post("/webhook/{bot_token}")
async def webhook_handler(bot_token: str, request: Request):
    """Handle incoming webhook updates from Telegram"""
    
    # Validate token
    if bot_token != BOT.TOKEN:
        logger.warning(f"Invalid token attempt: {bot_token[:10]}...")
        raise HTTPException(status_code=404, detail="Not found")
    
    # Wait for bot to be ready
    try:
        await asyncio.wait_for(bot_ready.wait(), timeout=10.0)
    except asyncio.TimeoutError:
        logger.error("Bot not ready - timeout")
        raise HTTPException(status_code=503, detail="Bot initializing")
    
    if not bot_instance:
        logger.error("Bot instance is None")
        raise HTTPException(status_code=503, detail="Bot not available")
    
    try:
        # Parse update
        update = await request.json()
        update_id = update.get("update_id")
        
        # Prevent duplicate processing
        if update_id and update_id in processed_updates:
            logger.debug(f"Duplicate update {update_id} skipped")
            return {"ok": True}
        
        if update_id:
            processed_updates.add(update_id)
            
            # Cleanup old updates
            if len(processed_updates) > MAX_UPDATE_CACHE:
                processed_updates.clear()
                logger.info("Update cache cleared")
        
        # Process update in background
        asyncio.create_task(process_update(update))
        
        return {"ok": True}
        
    except Exception as e:
        logger.error(f"Webhook handler error: {e}", exc_info=True)
        return {"ok": True}  # Always return OK to Telegram


async def process_update(update: dict):
    """
    ✅ WORKING METHOD: Process update through Telegram Bot API
    Uses bot.get_messages() to properly fetch message with peer data
    """
    try:
        # Handle new messages
        if "message" in update:
            msg_data = update["message"]
            chat_id = msg_data.get("chat", {}).get("id")
            message_id = msg_data.get("message_id")
            
            if not chat_id or not message_id:
                return
            
            try:
                # ✅ CRITICAL FIX: Fetch message properly using Pyrogram
                # This resolves peer_id automatically
                message = await bot_instance.get_messages(chat_id, message_id)
                
                # Process through all handlers
                for group in sorted(bot_instance.dispatcher.groups.keys()):
                    handlers = bot_instance.dispatcher.groups[group]
                    
                    for handler in handlers:
                        try:
                            # Check if handler matches
                            if await handler.check(bot_instance, message):
                                await handler.callback(bot_instance, message)
                                break  # Stop after first matching handler
                        except Exception as e:
                            logger.error(f"Handler error: {e}", exc_info=True)
                            
            except PeerIdInvalid:
                logger.warning(f"PeerIdInvalid for chat {chat_id} - skipping")
            except Exception as e:
                logger.error(f"Message processing error: {e}", exc_info=True)
        
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
                logger.warning(f"PeerIdInvalid for edited message - skipping")
            except Exception as e:
                logger.error(f"Edited message error: {e}", exc_info=True)
        
        # Handle callback queries (buttons)
        elif "callback_query" in update:
            # Callback queries work differently - need to handle via raw data
            # For now, we'll skip complex parsing
            logger.info("Callback query received - implement if needed")
            
    except Exception as e:
        logger.error(f"Update processing error: {e}", exc_info=True)


# =============================
# Bot Class
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
            no_updates=True  # ✅ Disable polling - we use webhooks
        )

    async def start(self):
        """Start bot and notify owner"""
        await super().start()
        
        # Get bot info
        me = await self.get_me()
        BOT.USERNAME = f"@{me.username}"
        self.mention = me.mention
        self.username = me.username
        
        logger.info(f"✅ Bot started: {me.first_name} (@{me.username})")
        
        # Try to notify owner
        try:
            await self.send_message(
                chat_id=OWNER.ID,
                text=f"✅ **{me.first_name} Started Successfully**\n\n"
                     f"🤖 Username: @{me.username}\n"
                     f"🆔 Bot ID: `{me.id}`\n"
                     f"🌐 Mode: Webhook"
            )
            logger.info(f"Startup notification sent to owner {OWNER.ID}")
        except PeerIdInvalid:
            logger.warning(f"Cannot send to owner {OWNER.ID} - PeerIdInvalid (send /start to bot first)")
        except Exception as e:
            logger.warning(f"Could not notify owner: {e}")

    async def stop(self, *args):
        """Stop bot gracefully"""
        await super().stop()
        logger.info("🛑 Bot stopped")


# =============================
# Webhook Setup
# =============================
async def setup_webhook(webhook_url: str):
    """Configure Telegram webhook"""
    try:
        import httpx
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Delete existing webhook
            logger.info("Deleting old webhook...")
            delete_resp = await client.post(
                f"https://api.telegram.org/bot{BOT.TOKEN}/deleteWebhook",
                json={"drop_pending_updates": True}
            )
            logger.info(f"Delete response: {delete_resp.json()}")
            
            await asyncio.sleep(2)
            
            # Set new webhook
            logger.info(f"Setting webhook: {webhook_url}")
            set_resp = await client.post(
                f"https://api.telegram.org/bot{BOT.TOKEN}/setWebhook",
                json={
                    "url": webhook_url,
                    "allowed_updates": ["message", "edited_message", "callback_query"],
                    "drop_pending_updates": True,
                    "max_connections": 40
                }
            )
            
            result = set_resp.json()
            if result.get("ok"):
                logger.info("✅ Webhook configured successfully")
                
                # Get webhook info
                info_resp = await client.get(
                    f"https://api.telegram.org/bot{BOT.TOKEN}/getWebhookInfo"
                )
                info = info_resp.json()
                logger.info(f"📡 Webhook info: {info}")
                
                return True
            else:
                logger.error(f"❌ Webhook setup failed: {result}")
                return False
                
    except Exception as e:
        logger.error(f"Webhook setup error: {e}", exc_info=True)
        return False


# =============================
# FastAPI Lifecycle
# =============================
@app.on_event("startup")
async def startup_event():
    """Initialize bot on startup"""
    global bot_instance
    
    logger.info("🚀 Starting bot initialization...")
    
    try:
        # Get webhook URL from environment
        WEBHOOK_URL = os.getenv("WEBHOOK_URL")
        if not WEBHOOK_URL:
            logger.error("❌ WEBHOOK_URL environment variable not set!")
            logger.error("Set it to: https://your-app.onrender.com/webhook/YOUR_BOT_TOKEN")
            return
        
        # Ensure /tmp directory exists
        os.makedirs("/tmp", exist_ok=True)
        
        # Initialize bot
        logger.info("Initializing Pyrogram client...")
        bot_instance = MN_Bot()
        
        # Start bot
        logger.info("Starting bot...")
        await bot_instance.start()
        
        # Setup webhook
        logger.info("Configuring webhook...")
        webhook_ok = await setup_webhook(WEBHOOK_URL)
        
        if webhook_ok:
            # Mark bot as ready
            bot_ready.set()
            logger.info("✅ Bot fully initialized and ready!")
            logger.info(f"📡 Listening for updates at: {WEBHOOK_URL}")
        else:
            logger.error("❌ Webhook setup failed - bot may not receive updates")
        
    except Exception as e:
        logger.error(f"❌ Bot initialization failed: {e}", exc_info=True)


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    global bot_instance
    
    logger.info("🛑 Shutting down...")
    
    if bot_instance:
        try:
            await bot_instance.stop()
            logger.info("Bot stopped gracefully")
        except Exception as e:
            logger.error(f"Error stopping bot: {e}")


# =============================
# Main Entry Point
# =============================
if __name__ == "__main__":
    import uvicorn
    
    PORT = int(os.getenv("PORT", 8000))
    
    logger.info(f"🌐 Starting FastAPI server on port {PORT}...")
    
    uvicorn.run(
        "bot:app",
        host="0.0.0.0",
        port=PORT,
        log_level="info",
        access_log=True,
        loop="asyncio"
    )
