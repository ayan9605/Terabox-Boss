import logging
import asyncio
import uvicorn
import os
from fastapi import FastAPI, Request, HTTPException
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

# Global bot instance and update tracker
bot_instance = None
bot_ready = asyncio.Event()  # ✅ Add ready flag
processed_updates = set()
MAX_UPDATE_CACHE = 1000

@app.get("/")
async def root():
    return {"status": "running", "message": "MnBot is running!"}

@app.get("/health")
async def health():
    return {"status": "healthy", "bot_ready": bot_ready.is_set()}

# =============================
# Webhook Endpoint
# =============================
@app.post(f"/webhook/{{bot_token}}")  # ✅ Use path parameter
async def webhook_handler(bot_token: str, request: Request):
    """
    Telegram webhook endpoint - receives updates from Telegram
    """
    # ✅ Verify bot token
    if bot_token != BOT.TOKEN:
        raise HTTPException(status_code=404, detail="Not found")
    
    # ✅ Wait for bot to be ready (max 30 seconds)
    try:
        await asyncio.wait_for(bot_ready.wait(), timeout=30.0)
    except asyncio.TimeoutError:
        logging.error("Bot initialization timeout")
        raise HTTPException(status_code=503, detail="Bot not ready")
    
    if bot_instance is None:
        logging.error("Bot instance is None after ready flag set")
        raise HTTPException(status_code=503, detail="Bot not initialized")
    
    try:
        update = await request.json()
        
        # Check for duplicate update_id
        update_id = update.get("update_id")
        if update_id in processed_updates:
            logging.info(f"⚠️ Duplicate update {update_id} ignored")
            return {"ok": True}
        
        # Track this update
        processed_updates.add(update_id)
        
        # Manage cache size
        if len(processed_updates) > MAX_UPDATE_CACHE:
            processed_updates.clear()
            logging.info("🔄 Update cache cleared")
        
        # Process in background
        asyncio.create_task(process_telegram_update(update))
        
        return {"ok": True}
    
    except Exception as e:
        logging.error(f"Error in webhook_handler: {e}", exc_info=True)
        return {"ok": True}  # Still return 200


async def process_telegram_update(update: dict):
    """
    Processes Telegram updates using Pyrogram's built-in system
    """
    try:
        from pyrogram import types
        
        # Handle MESSAGE updates
        if "message" in update:
            message_data = update["message"]
            message = types.Message._parse(
                bot_instance, 
                message_data, 
                users={}, 
                chats={}
            )
            
            # Use Pyrogram's dispatcher
            for group in sorted(bot_instance.dispatcher.groups.keys()):
                handlers = bot_instance.dispatcher.groups[group]
                
                for handler in handlers:
                    try:
                        if await handler.check(bot_instance, message):
                            await handler.callback(bot_instance, message)
                            break
                    except Exception as e:
                        logging.error(f"Handler error: {e}", exc_info=True)
                        continue
        
        # Handle EDITED MESSAGE updates
        elif "edited_message" in update:
            message_data = update["edited_message"]
            message = types.Message._parse(
                bot_instance, 
                message_data, 
                users={}, 
                chats={}
            )
            
            for group in sorted(bot_instance.dispatcher.groups.keys()):
                handlers = bot_instance.dispatcher.groups[group]
                
                for handler in handlers:
                    try:
                        if await handler.check(bot_instance, message):
                            await handler.callback(bot_instance, message)
                            break
                    except Exception as e:
                        logging.error(f"Handler error: {e}", exc_info=True)
                        continue
        
        # Handle CALLBACK QUERY updates
        elif "callback_query" in update:
            callback_data = update["callback_query"]
            callback = types.CallbackQuery._parse(
                bot_instance, 
                callback_data, 
                users={}
            )
            
            for group in sorted(bot_instance.dispatcher.groups.keys()):
                handlers = bot_instance.dispatcher.groups[group]
                
                for handler in handlers:
                    try:
                        if await handler.check(bot_instance, callback):
                            await handler.callback(bot_instance, callback)
                            break
                    except Exception as e:
                        logging.error(f"Handler error: {e}", exc_info=True)
                        continue
                        
    except Exception as e:
        logging.error(f"Error in process_telegram_update: {e}", exc_info=True)


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
                text=f"✅ {me.first_name} BOT started successfully ✅✅"
            )
        except FloodWait as e:
            await asyncio.sleep(e.value)
            await self.send_message(
                chat_id=OWNER.ID,
                text=f"✅ {me.first_name} BOT started successfully ✅✅"
            )

        logging.info(f"✅ {me.first_name} BOT started successfully")

    async def stop(self, *args):
        await super().stop()
        logging.info("🚫 Bot Stopped")


# =============================
# Webhook Setup Function
# =============================
async def setup_webhook(bot: MN_Bot, webhook_url: str):
    """
    Configures Telegram webhook
    """
    try:
        import httpx
        
        async with httpx.AsyncClient() as client:
            # Clear old webhook
            delete_response = await client.post(
                f"https://api.telegram.org/bot{BOT.TOKEN}/deleteWebhook",
                json={"drop_pending_updates": True}
            )
            logging.info(f"Old webhook deleted: {delete_response.json()}")
            
            await asyncio.sleep(2)
            
            # Set new webhook
            set_response = await client.post(
                f"https://api.telegram.org/bot{BOT.TOKEN}/setWebhook",
                json={
                    "url": webhook_url,
                    "allowed_updates": ["message", "edited_message", "callback_query"],
                    "drop_pending_updates": True,
                    "max_connections": 40
                }
            )
            result = set_response.json()
            
            if result.get("ok"):
                logging.info(f"✅ Webhook set successfully: {webhook_url}")
                
                info_response = await client.get(
                    f"https://api.telegram.org/bot{BOT.TOKEN}/getWebhookInfo"
                )
                logging.info(f"📡 Webhook info: {info_response.json()}")
            else:
                logging.error(f"❌ Failed to set webhook: {result}")
                
    except Exception as e:
        logging.error(f"Error setting webhook: {e}")


# =============================
# Startup Event
# =============================
@app.on_event("startup")
async def startup_event():
    """Initialize bot on FastAPI startup"""
    global bot_instance
    
    logging.info("🚀 Starting bot initialization...")
    
    try:
        WEBHOOK_URL = os.getenv("WEBHOOK_URL")
        
        if not WEBHOOK_URL:
            logging.error("❌ WEBHOOK_URL environment variable not set!")
            return
        
        # Initialize bot
        bot_instance = MN_Bot()
        await bot_instance.start()
        
        # Setup webhook
        await setup_webhook(bot_instance, WEBHOOK_URL)
        
        # ✅ Set ready flag
        bot_ready.set()
        logging.info("✅ Bot fully initialized and ready!")
        
    except Exception as e:
        logging.error(f"❌ Bot initialization failed: {e}", exc_info=True)


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    global bot_instance
    
    if bot_instance:
        try:
            await bot_instance.stop()
            logging.info("🚫 Bot stopped gracefully")
        except Exception as e:
            logging.error(f"Error stopping bot: {e}")


# =============================
# Main Entry Point (Alternative)
# =============================
if __name__ == "__main__":
    import uvicorn
    
    PORT = int(os.getenv("PORT", 8000))
    
    logging.info(f"🚀 Starting server on port {PORT}...")
    
    uvicorn.run(
        "bot:app",
        host="0.0.0.0",
        port=PORT,
        log_level="info",
        access_log=True
    )
