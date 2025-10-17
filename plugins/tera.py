import os
import tempfile
import requests
import asyncio
import time
import mimetypes
from pyrogram import Client 
from pyrogram import filters
from pyrogram.types import Message
from verify_patch import IS_VERIFY, is_verified, build_verification_link, HOW_TO_VERIFY
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
import shutil
from config import CHANNEL, DATABASE
from collections import defaultdict
from typing import List, Dict

mongo_client = MongoClient(DATABASE.URI)
db = mongo_client[DATABASE.NAME]

settings_col = db["terabox_settings"]
queue_col = db["terabox_queue"]
last_upload_col = db["terabox_lastupload"]

TERABOX_REGEX = r'https?://(?:www\.)?[^/\s]*tera[^/\s]*\.[a-z]+/s/[^\s]+'

# API Configuration
API_BASE_URL = "https://terabox-fastapi.lily445545.workers.dev"

# ✅ Local cache for folder downloads (in-memory, super fast)
folder_cache = {}
MAX_CONCURRENT_DOWNLOADS = 3  # Download 3 files simultaneously
MAX_FOLDER_SIZE = 2 * 1024 * 1024 * 1024  # 2GB max folder size

def get_file_info_from_api(share_url: str) -> dict:
    """
    Fetch file information from TeraBox FastAPI
    
    Args:
        share_url: TeraBox share URL
        
    Returns:
        dict with file information including download link(s)
        
    Raises:
        ValueError: If API request fails or returns error
    """
    try:
        api_url = f"{API_BASE_URL}/api?url={share_url}"
        response = requests.get(api_url, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        if not data.get("ok"):
            raise ValueError("API returned error response")
            
        if not data.get("files") or len(data["files"]) == 0:
            raise ValueError("No files found in the response")
        
        files = data["files"]
        
        # ✅ Check if it's a folder (multiple files)
        is_folder = len(files) > 1
        
        if is_folder:
            # Return all files info
            return {
                "is_folder": True,
                "folder_name": data.get("folder_name", "TeraBox Folder"),
                "files": [
                    {
                        "name": f.get("name", "download"),
                        "download_link": f.get("fast_download", ""),
                        "size_str": f.get("size", "Unknown"),
                        "size_bytes": f.get("bytes", 0),
                        "thumb": f.get("thumb", ""),
                        "stream_link": f.get("stream", "")
                    }
                    for f in files
                ],
                "total_size": sum(f.get("bytes", 0) for f in files),
                "file_count": len(files)
            }
        else:
            # Single file
            file_info = files[0]
            return {
                "is_folder": False,
                "name": file_info.get("name", "download"),
                "download_link": file_info.get("fast_download", ""),
                "size_str": file_info.get("size", "Unknown"),
                "size_bytes": file_info.get("bytes", 0),
                "thumb": file_info.get("thumb", ""),
                "stream_link": file_info.get("stream", "")
            }
        
    except requests.RequestException as e:
        raise ValueError(f"API request failed: {str(e)}")
    except (KeyError, IndexError) as e:
        raise ValueError(f"Invalid API response format: {str(e)}")


def get_size(bytes_len: int) -> str:
    """Convert bytes to human-readable format"""
    if bytes_len >= 1024 ** 3:
        return f"{bytes_len / 1024**3:.2f} GB"
    if bytes_len >= 1024 ** 2:
        return f"{bytes_len / 1024**2:.2f} MB"
    if bytes_len >= 1024:
        return f"{bytes_len / 1024:.2f} KB"
    return f"{bytes_len} bytes"


def detect_file_type(filename: str) -> str:
    """
    Detect file type based on extension
    
    Args:
        filename: Name of the file
        
    Returns:
        'video', 'photo', or 'document'
    """
    mime_type, _ = mimetypes.guess_type(filename)
    
    if mime_type:
        if mime_type.startswith('video/'):
            return 'video'
        elif mime_type.startswith('image/'):
            return 'photo'
    
    # Fallback to extension checking
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
    """
    Generate a visual progress bar
    
    Args:
        percentage: Progress percentage (0-100)
        
    Returns:
        String representing the progress bar
    """
    # Progress bar with 20 blocks
    filled_blocks = int(percentage / 5)
    empty_blocks = 20 - filled_blocks
    
    bar = "█" * filled_blocks + "░" * empty_blocks
    return f"[{bar}]"


def format_time(seconds: int) -> str:
    """
    Format seconds into readable time string
    
    Args:
        seconds: Time in seconds
        
    Returns:
        Formatted time string (e.g., "2h 30m 15s" or "45s")
    """
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
    """
    Calculate download speed
    
    Args:
        downloaded: Bytes downloaded
        elapsed_time: Time elapsed in seconds
        
    Returns:
        Formatted speed string
    """
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


async def download_single_file_from_folder(
    file_info: dict,
    temp_dir: str,
    semaphore: asyncio.Semaphore,
    progress_tracker: dict
) -> dict:
    """
    Download a single file from folder concurrently
    
    Args:
        file_info: File information dict
        temp_dir: Temporary directory to save file
        semaphore: Asyncio semaphore for limiting concurrent downloads
        progress_tracker: Shared dict to track download progress
        
    Returns:
        dict with download result
    """
    async with semaphore:
        try:
            filename = file_info["name"]
            temp_path = os.path.join(temp_dir, filename)
            
            # Download file
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: download_file_sync(
                    file_info["download_link"],
                    temp_path,
                    filename,
                    progress_tracker
                )
            )
            
            return {
                "success": True,
                "filename": filename,
                "path": temp_path,
                "size": file_info["size_bytes"],
                "file_type": detect_file_type(filename)
            }
            
        except Exception as e:
            return {
                "success": False,
                "filename": file_info["name"],
                "error": str(e)
            }


def download_file_sync(url: str, path: str, filename: str, progress_tracker: dict):
    """Synchronous file download for executor"""
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total_size = int(r.headers.get('content-length', 0))
        
        with open(path, "wb") as f:
            downloaded = 0
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    # Update progress tracker
                    progress_tracker[filename] = {
                        "downloaded": downloaded,
                        "total": total_size,
                        "percentage": (downloaded / total_size * 100) if total_size > 0 else 0
                    }


async def handle_folder_download(client: Client, message: Message, folder_info: dict, url: str):
    """
    Handle folder download with concurrent file downloads
    
    Args:
        client: Pyrogram client
        message: User message
        folder_info: Folder information from API
        url: Original TeraBox URL
    """
    folder_name = folder_info["folder_name"]
    files = folder_info["files"]
    total_size = folder_info["total_size"]
    file_count = folder_info["file_count"]
    
    # Check folder size limit
    if total_size > MAX_FOLDER_SIZE:
        await message.reply(
            f"❌ **Folder too large!**\n\n"
            f"**Folder Size:** {get_size(total_size)}\n"
            f"**Max Allowed:** {get_size(MAX_FOLDER_SIZE)}\n\n"
            f"Please download files individually."
        )
        return
    
    status_msg = await message.reply(
        f"📁 **Folder Detected!**\n\n"
        f"**Name:** `{folder_name}`\n"
        f"**Files:** {file_count}\n"
        f"**Total Size:** {get_size(total_size)}\n\n"
        f"⏳ Starting downloads..."
    )
    
    # Create temporary directory for folder
    temp_dir = os.path.join(tempfile.gettempdir(), f"terabox_{int(time.time())}")
    os.makedirs(temp_dir, exist_ok=True)
    
    try:
        # Progress tracker (shared across all downloads)
        progress_tracker = {}
        
        # Semaphore to limit concurrent downloads
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
        
        # Create download tasks
        tasks = [
            download_single_file_from_folder(file_info, temp_dir, semaphore, progress_tracker)
            for file_info in files
        ]
        
        # Monitor progress
        download_task = asyncio.create_task(asyncio.gather(*tasks))
        
        # Update progress while downloading
        start_time = time.time()
        while not download_task.done():
            await asyncio.sleep(2)
            
            completed = sum(1 for f in progress_tracker.values() if f["percentage"] >= 100)
            total_downloaded = sum(f["downloaded"] for f in progress_tracker.values())
            overall_percentage = (total_downloaded / total_size * 100) if total_size > 0 else 0
            elapsed = time.time() - start_time
            speed = calculate_speed(total_downloaded, elapsed)
            
            progress_text = (
                f"📥 **DOWNLOADING FOLDER**\n\n"
                f"**Folder:** `{folder_name[:25]}{'...' if len(folder_name) > 25 else ''}`\n"
                f"**Progress:** {completed}/{file_count} files\n\n"
                f"**PROCESS:**\n"
                f"{progress_bar(overall_percentage)}\n\n"
                f"**Speed:** {speed}\n"
                f"**Overall:** {overall_percentage:.1f}%\n"
                f"**Downloaded:** {get_size(total_downloaded)} / {get_size(total_size)}"
            )
            
            try:
                await status_msg.edit(progress_text)
            except:
                pass
        
        # Get results
        results = await download_task
        successful = [r for r in results if r["success"]]
        failed = [r for r in results if not r["success"]]
        
        if failed:
            await status_msg.edit(
                f"⚠️ **Download completed with errors**\n\n"
                f"✅ Successful: {len(successful)}/{file_count}\n"
                f"❌ Failed: {len(failed)}\n\n"
                f"Uploading successful files..."
            )
        else:
            await status_msg.edit(
                f"✅ **All files downloaded!**\n\n"
                f"📤 Uploading {len(successful)} files to Telegram..."
            )
        
        # Upload files to Telegram
        uploaded_count = 0
        for result in successful:
            try:
                caption = (
                    f"📄 **File:** `{result['filename']}`\n"
                    f"📦 **Size:** {get_size(result['size'])}\n"
                    f"📁 **From Folder:** {folder_name}\n\n"
                    f"⚡ Powered by @A.Sayyad"
                )
                
                # Send based on file type
                if result['file_type'] == 'video':
                    await client.send_video(
                        chat_id=message.chat.id,
                        video=result['path'],
                        caption=caption,
                        has_spoiler=True,
                        supports_streaming=True,
                        protect_content=True
                    )
                elif result['file_type'] == 'photo':
                    await client.send_photo(
                        chat_id=message.chat.id,
                        photo=result['path'],
                        caption=caption,
                        has_spoiler=True,
                        protect_content=True
                    )
                else:
                    await client.send_document(
                        chat_id=message.chat.id,
                        document=result['path'],
                        caption=caption,
                        file_name=result['filename'],
                        protect_content=True
                    )
                
                uploaded_count += 1
                
                # Update progress
                if uploaded_count % 3 == 0:
                    try:
                        await status_msg.edit(
                            f"📤 **Uploading...**\n\n"
                            f"Uploaded: {uploaded_count}/{len(successful)} files"
                        )
                    except:
                        pass
                    
            except Exception as e:
                print(f"Failed to upload {result['filename']}: {e}")
        
        await status_msg.edit(
            f"✅ **Folder upload complete!**\n\n"
            f"📁 **Folder:** {folder_name}\n"
            f"📤 **Uploaded:** {uploaded_count}/{file_count} files\n"
            f"📦 **Total Size:** {get_size(total_size)}"
        )
        
    except Exception as e:
        await status_msg.edit(f"❌ **Folder download failed:**\n`{str(e)}`")
    finally:
        # Cleanup temp directory
        if os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except:
                pass


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
        info = get_file_info_from_api(url)
    except Exception as e:
        await status_msg.edit(f"❌ Failed to get file info:\n`{e}`")
        return

    # ✅ Check if it's a folder
    if info.get("is_folder"):
        await status_msg.delete()
        await handle_folder_download(client, message, info, url)
        return
    
    # ✅ Single file handling (your existing code)
    if not info["download_link"]:
        await status_msg.edit("❌ Could not retrieve download link")
        return

    temp_path = os.path.join(tempfile.gettempdir(), info["name"])
    file_type = detect_file_type(info["name"])

    # ... (rest of your single file download code remains the same)
    # [Keep all your existing single file download/upload code here]
