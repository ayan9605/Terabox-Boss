#please give credits https://github.com/MN-BOTS
#  @MrMNTG @MusammilN
import os
import tempfile
import aiohttp
import asyncio
import time
import mimetypes
import json
from pyrogram import Client 
from pyrogram import filters
from pyrogram.types import Message
from verify_patch import IS_VERIFY, is_verified, build_verification_link, HOW_TO_VERIFY
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from tempfile import SpooledTemporaryFile
from config import CHANNEL, DATABASE

# ✅ Optimized MongoDB connection pool
mongo_client = MongoClient(
    DATABASE.URI,
    maxPoolSize=50,
    minPoolSize=10,
    maxIdleTimeMS=45000,
    connect=False
)
db = mongo_client[DATABASE.NAME]

settings_col = db["terabox_settings"]
queue_col = db["terabox_queue"]
last_upload_col = db["terabox_lastupload"]

TERABOX_REGEX = r'https?://(?:www\.)?[^/\s]*tera[^/\s]*\.[a-z]+/s/[^\s]+'
API_BASE_URL = "https://terabox-fastapi.lily445545.workers.dev"

# ✅ Reusable aiohttp session
session = None

async def get_session():
    global session
    if session is None or session.closed:
        session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=300),
            connector=aiohttp.TCPConnector(limit=100, limit_per_host=30)
        )
    return session


async def get_file_info_from_api(share_url: str) -> dict:
    """
    ✅ FIXED: Fetch file information using async aiohttp
    Handles text/plain content-type and proper type conversions
    """
    try:
        sess = await get_session()
        api_url = f"{API_BASE_URL}/api?url={share_url}"
        
        async with sess.get(api_url) as response:
            response.raise_for_status()
            
            # ✅ FIX: Read as text first, then parse JSON manually
            # This bypasses aiohttp's strict content-type validation
            text_response = await response.text()
            
            try:
                data = json.loads(text_response)
            except json.JSONDecodeError as je:
                raise ValueError(f"Invalid JSON response: {text_response[:200]}")
            
            if not data.get("ok"):
                error_msg = data.get("error", "Unknown error")
                raise ValueError(f"API error: {error_msg}")
                
            if not data.get("files") or len(data["files"]) == 0:
                raise ValueError("No files found in the response")
            
            file_info = data["files"][0]
            
            # ✅ FIX: Convert size_bytes to integer safely
            size_bytes_raw = file_info.get("bytes", 0)
            try:
                if isinstance(size_bytes_raw, str):
                    # Remove any non-numeric characters and convert
                    size_bytes = int(''.join(filter(str.isdigit, size_bytes_raw)) or '0')
                elif isinstance(size_bytes_raw, (int, float)):
                    size_bytes = int(size_bytes_raw)
                else:
                    size_bytes = 0
            except (ValueError, TypeError):
                size_bytes = 0
            
            return {
                "name": file_info.get("name", "download"),
                "download_link": file_info.get("fast_download", ""),
                "size_str": file_info.get("size", "Unknown"),
                "size_bytes": size_bytes,  # ✅ Now guaranteed to be int
                "thumb": file_info.get("thumb", ""),
                "stream_link": file_info.get("stream", ""),
                "file_type": detect_file_type(file_info.get("name", ""))
            }
            
    except aiohttp.ClientError as e:
        raise ValueError(f"Network error: {str(e)}")
    except (KeyError, IndexError) as e:
        raise ValueError(f"Invalid API response format: {str(e)}")


def get_size(bytes_len: int) -> str:
    """Convert bytes to human-readable format"""
    try:
        bytes_len = int(bytes_len)
    except (ValueError, TypeError):
        bytes_len = 0
        
    if bytes_len >= 1024 ** 3:
        return f"{bytes_len / 1024**3:.2f} GB"
    if bytes_len >= 1024 ** 2:
        return f"{bytes_len / 1024**2:.2f} MB"
    if bytes_len >= 1024:
        return f"{bytes_len / 1024:.2f} KB"
    return f"{bytes_len} bytes"


def detect_file_type(filename: str) -> str:
    """Detect file type based on extension"""
    if not filename:
        return 'document'
        
    mime_type, _ = mimetypes.guess_type(filename)
    
    if mime_type:
        if mime_type.startswith('video/'):
            return 'video'
        elif mime_type.startswith('image/'):
            return 'photo'
    
    video_extensions = ['.mp4', '.mkv', '.avi', '.mov', '.flv', '.wmv', '.webm', '.m4v', '.3gp']
    image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff']
    
    ext = os.path.splitext(filename.lower())[1]
    
    if ext in video_extensions:
        return 'video'
    elif ext in image_extensions:
        return 'photo'
    else:
        return 'document'


def progress_bar(percentage: float) -> str:
    """Generate a visual progress bar"""
    try:
        percentage = float(percentage)
    except (ValueError, TypeError):
        percentage = 0.0
        
    filled_blocks = int(percentage / 5)
    empty_blocks = 20 - filled_blocks
    bar = "█" * filled_blocks + "░" * empty_blocks
    return f"[{bar}]"


def format_time(seconds: int) -> str:
    """Format seconds into readable time string"""
    try:
        seconds = int(seconds)
    except (ValueError, TypeError):
        seconds = 0
        
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        mins = seconds // 60
        secs = seconds % 60
        return f"{mins}m {secs}s"
    else:
        hours = seconds // 3600
        mins = (seconds % 3600) // 60
        return f"{hours}h {mins}m"


def calculate_speed(downloaded: int, elapsed_time: float) -> str:
    """Calculate download speed"""
    try:
        downloaded = int(downloaded)
        elapsed_time = float(elapsed_time)
    except (ValueError, TypeError):
        return "0 B/s"
        
    if elapsed_time == 0:
        return "0 B/s"
    
    speed = downloaded / elapsed_time
    
    if speed >= 1024 ** 3:
        return f"{speed / 1024**3:.2f} GB/s"
    elif speed >= 1024 ** 2:
        return f"{speed / 1024**2:.2f} MB/s"
    elif speed >= 1024:
        return f"{speed / 1024:.2f} KB/s"
    else:
        return f"{speed:.2f} B/s"


async def download_file_async(url: str, temp_path: str, info: dict, status_msg):
    """
    ✅ Async download using aiohttp with optimized buffering
    """
    start_time = time.time()
    last_update = start_time
    downloaded = 0
    
    # ✅ FIX: Safe type conversion before comparison
    try:
        size_bytes = int(info.get("size_bytes", 0))
    except (ValueError, TypeError):
        size_bytes = 0
    
    # Use in-memory buffer for files < 100MB
    use_memory = size_bytes > 0 and size_bytes < 100 * 1024 * 1024
    
    if use_memory:
        file_obj = SpooledTemporaryFile(max_size=100*1024*1024, mode='w+b')
    else:
        file_obj = open(temp_path, 'wb')
    
    try:
        sess = await get_session()
        async with sess.get(url) as response:
            response.raise_for_status()
            total_size = int(response.headers.get('content-length', 0))
            
            # ✅ Buffered writing
            chunk_buffer = []
            buffer_size = 0
            max_buffer = 10 * 1024 * 1024  # 10MB buffer
            
            async for chunk in response.content.iter_chunked(2 * 1024 * 1024):  # 2MB chunks
                chunk_buffer.append(chunk)
                buffer_size += len(chunk)
                downloaded += len(chunk)
                
                # Write when buffer is full
                if buffer_size >= max_buffer:
                    file_obj.write(b''.join(chunk_buffer))
                    chunk_buffer = []
                    buffer_size = 0
                
                current_time = time.time()
                elapsed = current_time - start_time
                
                if current_time - last_update >= 2:
                    last_update = current_time
                    percentage = (downloaded / total_size * 100) if total_size > 0 else 0
                    speed = calculate_speed(downloaded, elapsed)
                    
                    if downloaded > 0 and elapsed > 0:
                        remaining_bytes = total_size - downloaded
                        bytes_per_second = downloaded / elapsed
                        eta_seconds = int(remaining_bytes / bytes_per_second) if bytes_per_second > 0 else 0
                        eta_str = format_time(eta_seconds)
                    else:
                        eta_str = "calculating..."
                    
                    progress_text = (
                        f"📥 **DOWNLOADING**\n\n"
                        f"**FILE NAME:** `{info['name'][:30]}{'...' if len(info['name']) > 30 else ''}`\n"
                        f"**SIZE:** {get_size(total_size)}\n\n"
                        f"**PROCESS:**\n"
                        f"{progress_bar(percentage)}\n\n"
                        f"**SPEED:** {speed}\n"
                        f"**PROGRESS:** {percentage:.1f}%\n\n"
                        f"**Downloaded:** {get_size(downloaded)}\n"
                        f"**ETA:** {eta_str}"
                    )
                    
                    try:
                        await status_msg.edit(progress_text)
                    except Exception:
                        pass
            
            # Write remaining buffer
            if chunk_buffer:
                file_obj.write(b''.join(chunk_buffer))
            
            # If using memory, write to disk now
            if use_memory:
                file_obj.seek(0)
                with open(temp_path, 'wb') as disk_file:
                    disk_file.write(file_obj.read())
                file_obj.close()
            else:
                file_obj.close()
                
    except Exception as e:
        if not file_obj.closed:
            file_obj.close()
        raise e


@Client.on_message(filters.private & filters.regex(TERABOX_REGEX))
async def handle_terabox(client, message: Message):
    user_id = message.from_user.id

    if IS_VERIFY and not await is_verified(user_id):
        verify_url = await build_verification_link(client.me.username, user_id)
        buttons = [
            [
                InlineKeyboardButton("✅ Verify Now", url=verify_url),
                InlineKeyboardButton("📖 Tutorial", url=HOW_TO_VERIFY)
            ]
        ]
        await message.reply_text(
            "🔐 You must verify before using this command.\n\n⏳ Verification lasts for 12 hours.",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    url = message.text.strip()
    status_msg = await message.reply("🔍 Fetching file info...")
    
    try:
        info = await get_file_info_from_api(url)
    except Exception as e:
        await status_msg.edit(f"❌ Failed to get file info:\n`{e}`")
        return

    if not info.get("download_link"):
        await status_msg.edit("❌ Could not retrieve download link")
        return

    temp_path = os.path.join(tempfile.gettempdir(), info["name"])
    file_type = info.get("file_type", "document")

    try:
        # ✅ Async download
        await download_file_async(info["download_link"], temp_path, info, status_msg)

        caption = (
            f"📄 **File Name:** `{info['name']}`\n"
            f"📦 **File Size:** {info['size_str']}\n"
            f"🔗 **Source:** [TeraBox Link]({url})\n\n"
            f"⚡ Powered by @MrMNTG"
        )
        
        upload_start = time.time()
        last_upload_update = upload_start
        
        async def upload_progress(current, total):
            nonlocal last_upload_update
            current_time = time.time()
            
            if current_time - last_upload_update < 2:
                return
                
            last_upload_update = current_time
            elapsed = current_time - upload_start
            percentage = (current / total) * 100
            speed = calculate_speed(current, elapsed)
            
            if current > 0 and elapsed > 0:
                remaining = total - current
                rate = current / elapsed
                eta = int(remaining / rate) if rate > 0 else 0
                eta_str = format_time(eta)
            else:
                eta_str = "calculating..."
            
            progress_text = (
                f"📤 **UPLOADING**\n\n"
                f"**FILE NAME:** `{info['name'][:30]}{'...' if len(info['name']) > 30 else ''}`\n"
                f"**SIZE:** {get_size(total)}\n\n"
                f"**PROCESS:**\n"
                f"{progress_bar(percentage)}\n\n"
                f"**SPEED:** {speed}\n"
                f"**PROGRESS:** {percentage:.1f}%\n\n"
                f"**Uploaded:** {get_size(current)}\n"
                f"**ETA:** {eta_str}"
            )
            
            try:
                await status_msg.edit(progress_text)
            except Exception:
                pass

        # Upload to channel first
        channel_msg = None
        if CHANNEL.ID:
            try:
                if file_type == 'video':
                    channel_msg = await client.send_video(
                        chat_id=CHANNEL.ID,
                        video=temp_path,
                        caption=caption,
                        file_name=info["name"],
                        has_spoiler=True,
                        supports_streaming=True,
                        progress=upload_progress
                    )
                elif file_type == 'photo':
                    channel_msg = await client.send_photo(
                        chat_id=CHANNEL.ID,
                        photo=temp_path,
                        caption=caption,
                        has_spoiler=True,
                        progress=upload_progress
                    )
                else:
                    channel_msg = await client.send_document(
                        chat_id=CHANNEL.ID,
                        document=temp_path,
                        caption=caption,
                        file_name=info["name"],
                        progress=upload_progress
                    )
            except Exception as e:
                print(f"Channel upload failed: {e}")

        # Send to user using file_id (instant!)
        if channel_msg:
            try:
                if file_type == 'video':
                    sent_msg = await client.send_video(
                        chat_id=message.chat.id,
                        video=channel_msg.video.file_id,
                        caption=caption,
                        protect_content=True,
                        has_spoiler=True,
                        supports_streaming=True
                    )
                elif file_type == 'photo':
                    sent_msg = await client.send_photo(
                        chat_id=message.chat.id,
                        photo=channel_msg.photo.file_id,
                        caption=caption,
                        protect_content=True,
                        has_spoiler=True
                    )
                else:
                    sent_msg = await client.send_document(
                        chat_id=message.chat.id,
                        document=channel_msg.document.file_id,
                        caption=caption,
                        file_name=info["name"],
                        protect_content=True
                    )
            except Exception as e:
                print(f"File_id sharing failed: {e}")
                channel_msg = None

        # Fallback to direct upload if channel upload failed
        if not channel_msg:
            if file_type == 'video':
                sent_msg = await client.send_video(
                    chat_id=message.chat.id,
                    video=temp_path,
                    caption=caption,
                    file_name=info["name"],
                    protect_content=True,
                    has_spoiler=True,
                    supports_streaming=True,
                    progress=upload_progress
                )
            elif file_type == 'photo':
                sent_msg = await client.send_photo(
                    chat_id=message.chat.id,
                    photo=temp_path,
                    caption=caption,
                    protect_content=True,
                    has_spoiler=True,
                    progress=upload_progress
                )
            else:
                sent_msg = await client.send_document(
                    chat_id=message.chat.id,
                    document=temp_path,
                    caption=caption,
                    file_name=info["name"],
                    protect_content=True,
                    progress=upload_progress
                )

        await status_msg.edit(
            f"✅ **File uploaded successfully as {file_type.upper()}!**\n\n"
            "⏰ Will be auto-deleted in 12 hours."
        )
        
        # Auto-delete after 12 hours
        await asyncio.sleep(43200)
        try:
            await sent_msg.delete()
            await status_msg.delete()
        except Exception:
            pass

    except Exception as e:
        await status_msg.edit(f"❌ **Error:**\n`{str(e)}`")
    finally:
        # Cleanup temp file
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass


# ✅ Cleanup on shutdown
async def cleanup():
    global session
    if session and not session.closed:
        await session.close()
