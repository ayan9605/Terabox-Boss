import logging
import asyncio
import uvicorn
import os
from fastapi import FastAPI, Request, HTTPException
from pyrogram import Client
from pyrogram.errors import FloodWait
from pyrogram.raw import types as raw_types
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
# Webhook Endpoint
# =============================
@app.post(f"/webhook/{{bot_token}}")
async def webhook_handler(bot_token: str, request: Request):
    """
    Telegram webhook endpoint
    """
    if bot_token != BOT.TOKEN:
        raise HTTPException(status_code=404, detail="Not found")
    
    try:
        await asyncio.wait_for(bot_ready.wait(), timeout=30.0)
    except asyncio.TimeoutError:
        logging.error("Bot initialization timeout")
        raise HTTPException(status_code=503, detail="Bot not ready")
    
    if bot_instance is None:
        logging.error("Bot instance is None")
        raise HTTPException(status_code=503, detail="Bot not initialized")
    
    try:
        update = await request.json()
        
        update_id = update.get("update_id")
        if update_id in processed_updates:
            logging.info(f"⚠️ Duplicate update {update_id} ignored")
            return {"ok": True}
        
        processed_updates.add(update_id)
        
        if len(processed_updates) > MAX_UPDATE_CACHE:
            processed_updates.clear()
            logging.info("🔄 Update cache cleared")
        
        asyncio.create_task(process_telegram_update(update))
        
        return {"ok": True}
    
    except Exception as e:
        logging.error(f"Error in webhook_handler: {e}", exc_info=True)
        return {"ok": True}


async def process_telegram_update(update: dict):
    """
    Processes Telegram updates properly with user/chat data
    """
    try:
        from pyrogram import types
        
        # ✅ Handle MESSAGE updates
        if "message" in update:
            message_data = update["message"]
            
            # ✅ CRITICAL: Fetch user and chat data properly
            users = {}
            chats = {}
            
            # Get user data
            if "from" in message_data:
                user_data = message_data["from"]
                user_id = user_data.get("id")
                if user_id:
                    users[user_id] = raw_types.User(
                        id=user_id,
                        is_self=False,
                        is_contact=False,
                        is_mutual_contact=False,
                        is_deleted=user_data.get("is_bot", False),
                        is_bot=user_data.get("is_bot", False),
                        is_verified=False,
                        is_restricted=False,
                        is_scam=False,
                        is_fake=False,
                        is_support=False,
                        first_name=user_data.get("first_name", ""),
                        last_name=user_data.get("last_name"),
                        username=user_data.get("username"),
                        language_code=user_data.get("language_code"),
                        phone=None,
                        photo=None,
                        restrictions=None,
                        status=None,
                        bot_info_version=None,
                        bot_inline_placeholder=None,
                        access_hash=0
                    )
            
            # Get chat data
            if "chat" in message_data:
                chat_data = message_data["chat"]
                chat_id = chat_data.get("id")
                chat_type = chat_data.get("type")
                
                if chat_id:
                    if chat_type == "private":
                        # For private chats, reuse user data
                        chats[chat_id] = users.get(chat_id, raw_types.User(
                            id=chat_id,
                            is_self=False,
                            is_contact=False,
                            is_mutual_contact=False,
                            is_deleted=False,
                            is_bot=False,
                            is_verified=False,
                            is_restricted=False,
                            is_scam=False,
                            is_fake=False,
                            is_support=False,
                            first_name=chat_data.get("first_name", "User"),
                            last_name=chat_data.get("last_name"),
                            username=chat_data.get("username"),
                            language_code=None,
                            phone=None,
                            photo=None,
                            restrictions=None,
                            status=None,
                            bot_info_version=None,
                            bot_inline_placeholder=None,
                            access_hash=0
                        ))
                    else:
                        # For groups/channels
                        chats[chat_id] = raw_types.Chat(
                            id=chat_id,
                            title=chat_data.get("title", "Group"),
                            photo=None,
                            participants_count=0,
                            date=0,
                            version=0,
                            migrated_to=None,
                            admin_rights=None,
                            default_banned_rights=None
                        )
            
            # ✅ CRITICAL: Await the async _parse method
            message = await types.Message._parse(
                bot_instance, 
                message_data, 
                users=users, 
                chats=chats
            )
            
            # Process through handlers
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
        
        # ✅ Handle EDITED MESSAGE updates
        elif "edited_message" in update:
            message_data = update["edited_message"]
            
            users = {}
            chats = {}
            
            if "from" in message_data:
                user_data = message_data["from"]
                user_id = user_data.get("id")
                if user_id:
                    users[user_id] = raw_types.User(
                        id=user_id,
                        is_self=False,
                        is_contact=False,
                        is_mutual_contact=False,
                        is_deleted=user_data.get("is_bot", False),
                        is_bot=user_data.get("is_bot", False),
                        is_verified=False,
                        is_restricted=False,
                        is_scam=False,
                        is_fake=False,
                        is_support=False,
                        first_name=user_data.get("first_name", ""),
                        last_name=user_data.get("last_name"),
                        username=user_data.get("username"),
                        language_code=user_data.get("language_code"),
                        phone=None,
                        photo=None,
                        restrictions=None,
                        status=None,
                        bot_info_version=None,
                        bot_inline_placeholder=None,
                        access_hash=0
                    )
            
            if "chat" in message_data:
                chat_data = message_data["chat"]
                chat_id = chat_data.get("id")
                if chat_id:
                    chats[chat_id] = users.get(chat_id, raw_types.User(
                        id=chat_id,
                        is_self=False,
                        is_contact=False,
                        is_mutual_contact=False,
                        is_deleted=False,
                        is_bot=False,
                        is_verified=False,
                        is_restricted=False,
                        is_scam=False,
                        is_fake=False,
                        is_support=False,
                        first_name=chat_data.get("first_name", "User"),
                        last_name=chat_data.get("last_name"),
                        username=chat_data.get("username"),
                        language_code=None,
                        phone=None,
                        photo=None,
                        restrictions=None,
                        status=None,
                        bot_info_version=None,
                        bot_inline_placeholder=None,
                        access_hash=0
                    ))
            
            message = await types.Message._parse(
                bot_instance, 
                message_data, 
                users=users, 
                chats=chats
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
        
        # ✅ Handle CALLBACK QUERY updates
        elif "callback_query" in update:
            callback_data = update["callback_query"]
            
            users = {}
            
            if "from" in callback_data:
                user_data = callback_data["from"]
                user_id = user_data.get("id")
                if user_id:
                    users[user_id] = raw_types.User(
                        id=user_id,
                        is_self=False,
                        is_contact=False,
                        is_mutual_contact=False,
                        is_deleted=user_data.get("is_bot", False),
                        is_bot=user_data.get("is_bot", False),
                        is_verified=False,
                        is_restricted=False,
                        is_scam=False,
                        is_fake=False,
                        is_support=False,
                        first_name=user_data.get("first_name", ""),
                        last_name=user_data.get("last_name"),
                        username=user_data.get("username"),
                        language_code=user_data.get("language_code"),
                        phone=None,
                        photo=None,
                        restrictions=None,
                        status=None,
                        bot_info_version=None,
                        bot_inline_placeholder=None,
                        access_hash=0
                    )
            
            callback = await types.CallbackQuery._parse(
                bot_instance, 
                callback_data, 
                users=users
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
            name="MN-Bot",
            api_id=API.ID,
            api_hash=API.HASH,
            bot_token=BOT.TOKEN,
            plugins=dict(root="plugins"),
            workers=16,
            workdir="/tmp"
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
                text=f"✅ {me.first_name} BOT started successfully"
            )
        except FloodWait as e:
            await asyncio.sleep(e.value)
            await self.send_message(
                chat_id=OWNER.ID,
                text=f"✅ {me.first_name} BOT started successfully"
            )
        except Exception as e:
            logging.warning(f"Could not send startup message to owner: {e}")

        logging.info(f"✅ {me.first_name} BOT started successfully")

    async def stop(self, *args):
        await super().stop()
        logging.info("🚫 Bot Stopped")


# =============================
# Webhook Setup
# =============================
async def setup_webhook(bot: MN_Bot, webhook_url: str):
    """
    Configures Telegram webhook
    """
    try:
        import httpx
        
        async with httpx.AsyncClient() as client:
            delete_response = await client.post(
                f"https://api.telegram.org/bot{BOT.TOKEN}/deleteWebhook",
                json={"drop_pending_updates": True}
            )
            logging.info(f"Old webhook deleted: {delete_response.json()}")
            
            await asyncio.sleep(2)
            
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
        
        os.makedirs("/tmp", exist_ok=True)
        
        bot_instance = MN_Bot()
        await bot_instance.start()
        
        await setup_webhook(bot_instance, WEBHOOK_URL)
        
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
# Main Entry Point
# =============================
if __name__ == "__main__":
    PORT = int(os.getenv("PORT", 8000))
    
    logging.info(f"🚀 Starting server on port {PORT}...")
    
    uvicorn.run(
        "bot:app",
        host="0.0.0.0",
        port=PORT,
        log_level="info",
        access_log=True
    )
