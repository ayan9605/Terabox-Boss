#please give credits https://github.com/MN-BOTS
#  @MrMNTG @MusammilN
import os
import tempfile
import asyncio
import time
import mimetypes
import aiohttp
import aiofiles
from pyrogram import Client 
from pyrogram import filters
from pyrogram.types import Message
from verify_patch import IS_VERIFY, is_verified, build_verification_link, HOW_TO_VERIFY
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
import shutil
from config import CHANNEL, DATABASE
#please give credits https://github.com/MN-BOTS
#  @MrMNTG @MusammilN

mongo_client = MongoClient(DATABASE.URI)
db = mongo_client[DATABASE.NAME]

settings_col = db["terabox_settings"]
queue_col = db["terabox_queue"]
last_upload_col = db["terabox_lastupload"]

TERABOX_REGEX = r'https?://(?:www\.)?[^/\s]*tera[^/\s]*\.[a-z]+/s/[^\s]+'

# Updated API Configuration
API_BASE_URL = "https://gold-newt-367030.hostingersite.com/tera.php"

async def get_file_info_from_api(share_url: str) -> dict:
    """
    Fetch file information from the new TeraBox API asynchronously
    """
    try:
        api_url = f"{API_BASE_URL}?url={share_url}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=30) as response:
                response.raise_for_status()
                data = await response.json()

                # ✅ Handle new JSON response format
                if data.get("success") and "data" in data and len(data["data"]) > 0:
                    file_info = data["data"][0]
                    return {
                        "name": file_info.get("file_name", "download") + file_info.get("extension", ""),
                        "download_link": file_info.get("download_url", ""),
                        "size_str": file_info.get("file_size", "Unknown"),
                        "size_bytes": file_info.get("file_size_bytes", 0),
                        "thumb": file_info.get("thumbnail", ""),
                        "stream_link": file_info.get("stream_final_url", "")
                    }

                raise ValueError("Invalid API response or missing download_url")

    except aiohttp.ClientError as e:
        raise ValueError(f"API request failed: {str(e)}")
    except Exception as e:
        raise ValueError(f"Error parsing API response: {str(e)}")


def get_size(bytes_len: int) -> str:
    if bytes_len >= 1024 ** 3:
        return f"{bytes_len / 1024**3:.2f} GB"
    if bytes_len >= 1024 ** 2:
        return f"{bytes_len / 1024**2:.2f} MB"
    if bytes_len >= 1024:
        return f"{bytes_len / 1024:.2f} KB"
    return f"{bytes_len} bytes"


def detect_file_type(filename: str) -> str:
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
    filled_blocks = int(percentage / 5)
    empty_blocks = 20 - filled_blocks
    bar = "█" * filled_blocks + "░" * empty_blocks
    return f"[{bar}]"


def format_time(seconds: int) -> str:
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
        info = await get_file_info_from_api(url)
    except Exception as e:
        await status_msg.edit(f"❌ Failed to get file info:\n`{e}`")
        return

    if not info["download_link"]:
        await status_msg.edit("❌ Could not retrieve download link")
        return

    temp_path = os.path.join(tempfile.gettempdir(), info["name"])
    file_type = detect_file_type(info["name"])

    start_time = time.time()
    last_update_time = start_time
    downloaded = 0

    try:
        # Download using aiohttp and aiofiles for MAXIMUM async speed
        async with aiohttp.ClientSession() as session:
            # None timeout is critical for large files
            async with session.get(info["download_link"], timeout=aiohttp.ClientTimeout(total=None)) as r:
                r.raise_for_status()
                total_size = int(r.headers.get('content-length', 0))

                # Non-blocking file write
                async with aiofiles.open(temp_path, "wb") as f:
                    chunk_size = 4 * 1024 * 1024  # 4MB chunks for extremely fast I/O throughput

                    async for chunk in r.content.iter_chunked(chunk_size):
                        if chunk:
                            await f.write(chunk)
                            downloaded += len(chunk)

                            current_time = time.time()
                            elapsed = current_time - start_time

                            # Update progress strictly every 3 seconds to avoid FloodWait
                            if current_time - last_update_time >= 3:
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
                                    f"📥 **DOWNLOADING (Turbo)**\n\n"
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

        await status_msg.edit("📤 **Preparing to upload to Telegram...**")

        caption = (
            f"📄 **File Name:** `{info['name']}`\n"
            f"📦 **File Size:** {info['size_str']}\n"
            f"🔗 **Source:** [TeraBox Link]({url})\n\n"
            f"⚡ Powered by @MrMNTG"
        )

        cancel_button = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ CANCEL", callback_data="cancel_upload")]
        ])

        if CHANNEL.ID:
            if file_type == 'video':
                await client.send_video(
                    chat_id=CHANNEL.ID,
                    video=temp_path,
                    caption=caption,
                    file_name=info["name"],
                    has_spoiler=True,
                    supports_streaming=True
                )
            elif file_type == 'photo':
                await client.send_photo(
                    chat_id=CHANNEL.ID,
                    photo=temp_path,
                    caption=caption,
                    has_spoiler=True
                )
            else:
                await client.send_document(
                    chat_id=CHANNEL.ID,
                    document=temp_path,
                    caption=caption,
                    file_name=info["name"]
                )

        upload_start = time.time()
        last_upload_update = upload_start

        async def upload_progress(current, total):
            nonlocal last_upload_update
            current_time = time.time()

            # Throttle to 3 seconds to avoid pyrogram FloodWait exceptions
            if current_time - last_upload_update < 3:
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
                f"📤 **UPLOADING (Turbo)**\n\n"
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
                await status_msg.edit(progress_text, reply_markup=cancel_button)
            except Exception:
                pass 

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

        await asyncio.sleep(43200)
        try:
            await sent_msg.delete()
            await status_msg.delete()
        except Exception:
            pass

    except aiohttp.ClientError as e:
        await status_msg.edit(f"❌ **Download failed:**\n`{str(e)}`")
    except Exception as e:
        await status_msg.edit(f"❌ **Upload failed:**\n`{str(e)}`")
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass
