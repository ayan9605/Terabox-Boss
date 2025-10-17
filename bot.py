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
processed_updates = set()  # Track processed update IDs
MAX_UPDATE_CACHE = 1000  # Prevent memory overflow

@app.get("/")
async def root():
    return {"status": "running", "message": "MnBot is running!"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

# =============================
# Webhook Endpoint
# =============================
@app.post(f"/webhook/{BOT.TOKEN}")
async def webhook_handler(request: Request):
    """
    Telegram webhook endpoint - receives updates from Telegram
    """
    if bot_instance is None:
        raise HTTPException(status_code=503, detail="Bot not initialized")
    
    try:
        update = await request.json()
        
        # ✅ CRITICAL: Check for duplicate update_id
        update_id = update.get("update_id")
        if update_id in processed_updates:
            logging.info(f"⚠️ Duplicate update {update_id} ignored")
            return {"ok": True}  # Return 200 OK immediately
        
        # Track this update
        processed_updates.add(update_id)
        
        # Manage cache size to prevent memory overflow
        if len(processed_updates) > MAX_UPDATE_CACHE:
            # Remove oldest half
            processed_updates.clear()
            logging.info("🔄 Update cache cleared")
        
        # ✅ IMPORTANT: Return 200 OK IMMEDIATELY, then process in background
        asyncio.create_task(process_telegram_update(update))
        
        return {"ok": True}
    
    except Exception as e:
        logging.error(f"Error in webhook_handler: {e}")
        # Still return 200 to prevent Telegram from retrying
        return {"ok": True}


async def process_telegram_update(update: dict):
    """
    Processes Telegram updates using Pyrogram's built-in system
    """
    try:
        # ✅ CORRECT IMPORT - Remove the problematic import
        from pyrogram import types
        
        # ✅ Handle MESSAGE updates
        if "message" in update:
            message_data = update["message"]
            message = types.Message._parse(
                bot_instance, 
                message_data, 
                users={}, 
                chats={}
            )
            
            # ✅ Use Pyrogram's dispatcher to handle the message
            # This will automatically trigger all registered handlers from plugins
            for group in sorted(bot_instance.dispatcher.groups.keys()):
                handlers = bot_instance.dispatcher.groups[group]
                
                for handler in handlers:
                    try:
                        # Check if handler accepts this message
                        if await handler.check(bot_instance, message):
                            await handler.callback(bot_instance, message)
                            break  # Stop after first matching handler in group
                    except Exception as e:
                        logging.error(f"Handler error: {e}")
                        continue
        
        # ✅ Handle EDITED MESSAGE updates
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
                        logging.error(f"Handler error: {e}")
                        continue
        
        # ✅ Handle CALLBACK QUERY updates (buttons)
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
                        logging.error(f"Handler error: {e}")
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
# Webhook Setup Function
# =============================
async def setup_webhook(bot: MN_Bot, webhook_url: str):
    """
    Configures Telegram webhook
    """
    try:
        import httpx
        
        # Delete webhook first and drop pending updates
        async with httpx.AsyncClient() as client:
            # ✅ Clear old webhook and pending updates
            delete_response = await client.post(
                f"https://api.telegram.org/bot{BOT.TOKEN}/deleteWebhook",
                json={"drop_pending_updates": True}
            )
            logging.info(f"Old webhook deleted: {delete_response.json()}")
            
            # Wait a bit for Telegram to process
            await asyncio.sleep(2)
            
            # ✅ Set new webhook
            set_response = await client.post(
                f"https://api.telegram.org/bot{BOT.TOKEN}/setWebhook",
                json={
                    "url": webhook_url,
                    "allowed_updates": ["message", "edited_message", "callback_query"],
                    "drop_pending_updates": True,  # Ignore old updates
                    "max_connections": 40  # Default
                }
            )
            result = set_response.json()
            
            if result.get("ok"):
                logging.info(f"✅ Webhook set successfully: {webhook_url}")
                
                # ✅ Verify webhook info
                info_response = await client.get(
                    f"https://api.telegram.org/bot{BOT.TOKEN}/getWebhookInfo"
                )
                logging.info(f"📡 Webhook info: {info_response.json()}")
            else:
                logging.error(f"❌ Failed to set webhook: {result}")
                
    except Exception as e:
        logging.error(f"Error setting webhook: {e}")


# =============================
# Main Runner
# =============================
async def main():
    global bot_instance
    
    # Get webhook URL from environment variable
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")  
    
    if not WEBHOOK_URL:
        logging.error("❌ WEBHOOK_URL environment variable not set!")
        logging.info("Example: WEBHOOK_URL=https://your-domain.com/webhook/{YOUR_BOT_TOKEN}")
        return

    bot_instance = MN_Bot()
    
    # Start bot (connects to Telegram but doesn't start polling)
    await bot_instance.start()
    
    # Setup webhook
    await setup_webhook(bot_instance, WEBHOOK_URL)

    # FastAPI server config
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        loop="asyncio",
        log_level="info"
    )
    server = uvicorn.Server(config)

    # Run FastAPI server
    try:
        logging.info("🚀 BOT and FastAPI webhook server are now running...")
        await server.serve()
    except (KeyboardInterrupt, SystemExit):
        logging.info("⚠ Shutdown signal received...")
    finally:
        await bot_instance.stop()


# =============================
# Entry Point
# =============================
if __name__ == "__main__":
    asyncio.run(main())
