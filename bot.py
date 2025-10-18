import logging
import asyncio
import uvicorn
import os
from fastapi import FastAPI, Request, HTTPException, Header
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

# Global bot instance
bot_instance = None

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
        
        # Process the update through Pyrogram's update handling system
        asyncio.create_task(process_telegram_update(update))
        
        # Immediately return 200 OK to Telegram
        return {"ok": True}
    except Exception as e:
        logging.error(f"Error processing webhook: {e}")
        # Still return 200 to prevent Telegram from retrying
        return {"ok": True}

async def process_telegram_update(update: dict):
    """
    Processes Telegram updates from Bot API format to Pyrogram handlers
    """
    try:
        from pyrogram import types
        from pyrogram.handlers import MessageHandler, CallbackQueryHandler
        
        # Handle regular messages
        if "message" in update:
            # Convert Bot API JSON to Pyrogram Message object using high-level parsing
            # Don't use _parse - instead reconstruct the Message from dict
            message_dict = update["message"]
            
            # Create a fake Update object that Pyrogram can process
            # Use Pyrogram's internal parsing by passing through the client
            message = types.Message._parse(
                client=bot_instance,
                message=message_dict,
                users={message_dict.get("from", {}).get("id"): types.User(
                    id=message_dict.get("from", {}).get("id"),
                    is_self=False,
                    is_contact=False,
                    is_mutual_contact=False,
                    is_deleted=False,
                    is_bot=message_dict.get("from", {}).get("is_bot", False),
                    is_verified=False,
                    is_restricted=False,
                    is_scam=False,
                    is_fake=False,
                    is_support=False,
                    first_name=message_dict.get("from", {}).get("first_name", ""),
                    last_name=message_dict.get("from", {}).get("last_name"),
                    username=message_dict.get("from", {}).get("username"),
                    language_code=message_dict.get("from", {}).get("language_code"),
                )} if message_dict.get("from") else {},
                chats={message_dict.get("chat", {}).get("id"): types.Chat(
                    id=message_dict.get("chat", {}).get("id"),
                    type=message_dict.get("chat", {}).get("type"),
                    title=message_dict.get("chat", {}).get("title"),
                    username=message_dict.get("chat", {}).get("username"),
                    first_name=message_dict.get("chat", {}).get("first_name"),
                    last_name=message_dict.get("chat", {}).get("last_name"),
                )} if message_dict.get("chat") else {}
            )
            
            # Iterate through all handler groups
            for group in sorted(bot_instance.dispatcher.groups.keys()):
                for handler in bot_instance.dispatcher.groups[group]:
                    if isinstance(handler, MessageHandler):
                        try:
                            # Check filters - they can be async coroutines
                            if handler.filters:
                                if asyncio.iscoroutinefunction(handler.filters):
                                    filter_result = await handler.filters(bot_instance, message)
                                elif callable(handler.filters):
                                    filter_check = handler.filters(bot_instance, message)
                                    if asyncio.iscoroutine(filter_check):
                                        filter_result = await filter_check
                                    else:
                                        filter_result = filter_check
                                else:
                                    filter_result = True
                                
                                if not filter_result:
                                    continue
                            
                            # Call the handler callback
                            await handler.callback(bot_instance, message)
                            
                        except Exception as e:
                            logging.error(f"Handler error: {e}", exc_info=True)
        
        # Handle edited messages
        elif "edited_message" in update:
            message_dict = update["edited_message"]
            
            message = types.Message._parse(
                client=bot_instance,
                message=message_dict,
                users={message_dict.get("from", {}).get("id"): types.User(
                    id=message_dict.get("from", {}).get("id"),
                    is_self=False,
                    is_contact=False,
                    is_mutual_contact=False,
                    is_deleted=False,
                    is_bot=message_dict.get("from", {}).get("is_bot", False),
                    is_verified=False,
                    is_restricted=False,
                    is_scam=False,
                    is_fake=False,
                    is_support=False,
                    first_name=message_dict.get("from", {}).get("first_name", ""),
                    last_name=message_dict.get("from", {}).get("last_name"),
                    username=message_dict.get("from", {}).get("username"),
                    language_code=message_dict.get("from", {}).get("language_code"),
                )} if message_dict.get("from") else {},
                chats={message_dict.get("chat", {}).get("id"): types.Chat(
                    id=message_dict.get("chat", {}).get("id"),
                    type=message_dict.get("chat", {}).get("type"),
                    title=message_dict.get("chat", {}).get("title"),
                    username=message_dict.get("chat", {}).get("username"),
                    first_name=message_dict.get("chat", {}).get("first_name"),
                    last_name=message_dict.get("chat", {}).get("last_name"),
                )} if message_dict.get("chat") else {}
            )
            
            for group in sorted(bot_instance.dispatcher.groups.keys()):
                for handler in bot_instance.dispatcher.groups[group]:
                    if isinstance(handler, MessageHandler):
                        try:
                            if handler.filters:
                                if asyncio.iscoroutinefunction(handler.filters):
                                    filter_result = await handler.filters(bot_instance, message)
                                elif callable(handler.filters):
                                    filter_check = handler.filters(bot_instance, message)
                                    if asyncio.iscoroutine(filter_check):
                                        filter_result = await filter_check
                                    else:
                                        filter_result = filter_check
                                else:
                                    filter_result = True
                                
                                if not filter_result:
                                    continue
                            
                            await handler.callback(bot_instance, message)
                            
                        except Exception as e:
                            logging.error(f"Handler error: {e}", exc_info=True)
        
        # Handle callback queries (button presses)
        elif "callback_query" in update:
            callback_dict = update["callback_query"]
            
            # Parse callback query
            callback = types.CallbackQuery._parse(
                client=bot_instance,
                callback_query=callback_dict,
                users={callback_dict.get("from", {}).get("id"): types.User(
                    id=callback_dict.get("from", {}).get("id"),
                    is_self=False,
                    is_contact=False,
                    is_mutual_contact=False,
                    is_deleted=False,
                    is_bot=callback_dict.get("from", {}).get("is_bot", False),
                    is_verified=False,
                    is_restricted=False,
                    is_scam=False,
                    is_fake=False,
                    is_support=False,
                    first_name=callback_dict.get("from", {}).get("first_name", ""),
                    last_name=callback_dict.get("from", {}).get("last_name"),
                    username=callback_dict.get("from", {}).get("username"),
                    language_code=callback_dict.get("from", {}).get("language_code"),
                )} if callback_dict.get("from") else {}
            )
            
            for group in sorted(bot_instance.dispatcher.groups.keys()):
                for handler in bot_instance.dispatcher.groups[group]:
                    if isinstance(handler, CallbackQueryHandler):
                        try:
                            if handler.filters:
                                if asyncio.iscoroutinefunction(handler.filters):
                                    filter_result = await handler.filters(bot_instance, callback)
                                elif callable(handler.filters):
                                    filter_check = handler.filters(bot_instance, callback)
                                    if asyncio.iscoroutine(filter_check):
                                        filter_result = await filter_check
                                    else:
                                        filter_result = filter_check
                                else:
                                    filter_result = True
                                
                                if not filter_result:
                                    continue
                            
                            await handler.callback(bot_instance, callback)
                            
                        except Exception as e:
                            logging.error(f"Handler error: {e}", exc_info=True)
                        
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
    webhook_url should be: https://your-domain.com/webhook/{BOT.TOKEN}
    """
    try:
        # Use Telegram Bot API to set webhook
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.telegram.org/bot{BOT.TOKEN}/setWebhook",
                json={
                    "url": webhook_url,
                    "allowed_updates": ["message", "edited_message", "callback_query"],
                    "drop_pending_updates": True  # Clear any pending updates
                }
            )
            result = response.json()
            if result.get("ok"):
                logging.info(f"✅ Webhook set successfully: {webhook_url}")
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
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # e.g., https://your-app.render.com/webhook/{BOT.TOKEN}
    
    if not WEBHOOK_URL:
        logging.error("❌ WEBHOOK_URL environment variable not set!")
        logging.info("Please set WEBHOOK_URL=https://your-domain.com/webhook/{BOT.TOKEN}")
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
