#please give credits https://github.com/MN-BOTS
#  @MrMNTG @MusammilN
import os
import tempfile
import requests  # ✅ Back to requests - faster for single downloads
import asyncio
import time
import mimetypes
from pyrogram import Client 
from pyrogram import filters
from pyrogram.types import Message
from verify_patch import IS_VERIFY, is_verified, build_verification_link, HOW_TO_VERIFY
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
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


def get_file_info_from_api(share_url: str) -> dict:
    """Fetch file information from TeraBox FastAPI"""
    try:
        api_url = f"{API_BASE_URL}/api?url={share_url}"
        response = requests.get(api_url, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        if not data.get("ok"):
            error_msg = data.get("error", "Unknown error")
            raise ValueError(f"API error: {error_msg}")
            
        if not data.get("files") or len(data["files"]) == 0:
            raise ValueError("No files found in the response")
        
        file_info = data["files"][0]
        
        # ✅ Safe type conversion
        size_bytes_raw = file_info.get("bytes", 0)
        try:
            if isinstance(size_bytes_raw, str):
                size_bytes = int(''.join(filter(str.isdigit, size_bytes_raw)) or '0')
            else:
                size_bytes = int(size_bytes_raw) if size_bytes_raw else 0
        except (ValueError, TypeError):
            size_bytes = 0
        
        return {
            "name": file_info.get("name", "download"),
            "download_link": file_info.get("fast_download", ""),
            "size_str": file_info.get("size", "Unknown"),
            "size_bytes": size_bytes,
            "thumb": file_info.get("thumb", ""),
            "stream_link": file_info.get("stream", ""),
            "file_type": detect_file_type(file_info.get("name", ""))
        }
        
    except requests.RequestException as e:
        raise ValueError(f"API request failed: {str(e)}")
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
        # ✅ Run blocking API call in executor to not block event loop
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, get_file_info_from_api, url)
    except Exception as e:
        await status_msg.edit(f"❌ Failed to get file info:\n`{e}`")
        return

    if not info.get("download_link"):
        await status_msg.edit("❌ Could not retrieve download link")
        return

    temp_path = os.path.join(tempfile.gettempdir(), info["name"])
    file_type = info.get("file_type", "document")

    # Download progress tracking
    start_time = time.time()
    last_update_time = start_time
    downloaded = 0

    try:
        # ✅ OPTIMIZED: Direct download with requests (faster for single files)
        with requests.get(info["download_link"], stream=True, timeout=60) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            
            # ✅ Write directly to disk (no extra memory copy)
            with open(temp_path, "wb") as f:
                # ✅ 4MB chunks - optimal for most systems
                chunk_size = 4 * 1024 * 1024
                
                for chunk in r.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        current_time = time.time()
                        elapsed = current_time - start_time
                        
                        # Update progress every 2 seconds
                        if current_time - last_update_time >= 2:
                            last_update_time = current_time
                            
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

        # ✅ Upload to channel first, then reuse file_id for user
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

        # ✅ Send to user using file_id (INSTANT - no second upload!)
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

        # Fallback to direct upload
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

    except requests.RequestException as e:
        await status_msg.edit(f"❌ **Download failed:**\n`{str(e)}`")
    except Exception as e:
        await status_msg.edit(f"❌ **Error:**\n`{str(e)}`")
    finally:
        # Cleanup temp file
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass
