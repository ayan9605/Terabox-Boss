# Credits: https://github.com/MN-BOTS | @MrMNTG @MusammilN
import os
import tempfile
import asyncio
import time
import mimetypes
import aiohttp
import aiofiles
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from config import CHANNEL, DATABASE
from verify_patch import IS_VERIFY, is_verified, build_verification_link, HOW_TO_VERIFY

# --- NITRO ENGINE INITIALIZATION ---
# Persistent session avoids the 'handshake' delay for every new link
aio_session = None

async def get_aio_session():
    global aio_session
    if aio_session is None:
        # High-concurrency connector
        connector = aiohttp.TCPConnector(limit=100, force_close=False)
        aio_session = aiohttp.ClientSession(connector=connector)
    return aio_session

TERABOX_REGEX = r'https?://(?:www\.)?[^/\s]*tera[^/\s]*\.[a-z]+/s/[^\s]+'
API_BASE_URL = "https://gold-newt-367030.hostingersite.com/tera.php"

# --- HELPER FUNCTIONS ---

def humanbytes(size):
    if not size: return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024: return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"

def get_progress_bar(percentage):
    blocks = int(percentage / 10)
    return "🎬" * blocks + "🌑" * (10 - blocks)

def detect_file_type(filename):
    mime, _ = mimetypes.guess_type(filename)
    if mime:
        if mime.startswith('video/'): return 'video'
        if mime.startswith('image/'): return 'photo'
    
    video_exts = ['.mp4', '.mkv', '.avi', '.mov', '.flv', '.wmv', '.webm', '.m4v']
    if any(filename.lower().endswith(ext) for ext in video_exts): return 'video'
    return 'document'

# --- CORE HANDLER ---

@Client.on_message(filters.private & filters.regex(TERABOX_REGEX))
async def handle_terabox(client, message: Message):
    user_id = message.from_user.id
    
    # 1. Verification Check
    if IS_VERIFY and not await is_verified(user_id):
        verify_url = await build_verification_link(client.me.username, user_id)
        buttons = [[InlineKeyboardButton("✅ Verify Now", url=verify_url),
                    InlineKeyboardButton("📖 Tutorial", url=HOW_TO_VERIFY)]]
        return await message.reply_text("🔐 Verification required to use Nitro speeds.", 
                                        reply_markup=InlineKeyboardMarkup(buttons))

    url = message.text.strip()
    status_msg = await message.reply("🚀 **Nitro Engine Starting...**")
    
    try:
        session = await get_aio_session()
        
        # 2. Fast API Fetch
        async with session.get(f"{API_BASE_URL}?url={url}", timeout=20) as api_resp:
            api_data = await api_resp.json()
            if not api_data.get("success"):
                return await status_msg.edit("❌ **API Error: Link not supported.**")
            
            f_info = api_data["data"][0]
            download_url = f_info.get("download_url")
            file_name = f_info.get("file_name") + f_info.get("extension", "")
            total_size = f_info.get("file_size_bytes", 0)

        temp_path = os.path.join(tempfile.gettempdir(), file_name)
        
        # 3. Double-Throttled Download
        start_time = time.time()
        last_update_time = 0
        last_percentage = 0
        downloaded = 0

        async with session.get(download_url, timeout=None) as resp:
            async with aiofiles.open(temp_path, "wb") as f:
                # 8MB Chunks for high-speed network utilization
                async for chunk in resp.content.iter_chunked(8 * 1024 * 1024):
                    await f.write(chunk)
                    downloaded += len(chunk)
                    
                    now = time.time()
                    diff = now - start_time
                    pc = (downloaded / total_size) * 100
                    
                    # NITRO LOGIC: Update every 5s OR 5% jump
                    if (now - last_update_time > 5) or (pc - last_percentage >= 5):
                        speed = downloaded / diff if diff > 0 else 0
                        eta = (total_size - downloaded) / speed if speed > 0 else 0
                        
                        try:
                            await status_msg.edit(
                                f"🏎️ **Nitro Downloading**\n\n"
                                f"📦 **Size:** {humanbytes(total_size)}\n"
                                f"⚡ **Speed:** {humanbytes(speed)}/s\n"
                                f"📊 **Progress:** {get_progress_bar(pc)} {pc:.1f}%\n"
                                f"⏳ **ETA:** {int(eta // 60)}m {int(eta % 60)}s"
                            )
                            last_update_time, last_percentage = now, pc
                        except: pass

        # 4. Optimized Upload
        await status_msg.edit("📤 **Download Finished! Igniting Upload...**")
        
        up_start = time.time()
        l_up_t, l_up_pc = 0, 0

        async def upload_progress(current, total):
            nonlocal l_up_t, l_up_pc
            now = time.time()
            pc = (current / total) * 100
            
            if (now - l_up_t > 5) or (pc - l_up_pc >= 5):
                diff = now - up_start
                speed = current / diff if diff > 0 else 0
                try:
                    await status_msg.edit(
                        f"🚀 **Nitro Uploading**\n\n"
                        f"⚡ **Speed:** {humanbytes(speed)}/s\n"
                        f"📊 **Progress:** {get_progress_bar(pc)} {pc:.1f}%"
                    )
                    l_up_t, l_up_pc = now, pc
                except: pass

        f_type = detect_file_type(file_name)
        caption = f"✅ **File:** `{file_name}`\n💰 **Size:** {humanbytes(total_size)}\n⚡ Powered by @MrMNTG"

        # Telegram specific optimization: supports_streaming=True
        if f_type == 'video':
            sent = await client.send_video(message.chat.id, video=temp_path, caption=caption, 
                                           progress=upload_progress, supports_streaming=True)
        elif f_type == 'photo':
            sent = await client.send_photo(message.chat.id, photo=temp_path, caption=caption)
        else:
            sent = await client.send_document(message.chat.id, document=temp_path, caption=caption, 
                                              progress=upload_progress)

        await status_msg.edit("🏁 **Mission Accomplished!**\nAuto-deleting in 12h.")
        
        # 5. Background Cleanup
        await asyncio.sleep(43200)
        try:
            await sent.delete()
            await status_msg.delete()
        except: pass

    except Exception as e:
        await status_msg.edit(f"💥 **Nitro Failure:** `{e}`")
    finally:
        if os.path.exists(temp_path): os.remove(temp_path)
