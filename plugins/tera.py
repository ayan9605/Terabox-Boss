#please give credits https://github.com/MN-BOTS
#  @MrMNTG @MusammilN
import os
import tempfile
import requests
import asyncio
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

# API Configuration
API_BASE_URL = "https://terabox-fastapi.lily445545.workers.dev"

def get_file_info_from_api(share_url: str) -> dict:
    """
    Fetch file information from TeraBox FastAPI
    
    Args:
        share_url: TeraBox share URL
        
    Returns:
        dict with file information including download link
        
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
        
        file_info = data["files"][0]
        
        return {
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

    if not info["download_link"]:
        await status_msg.edit("❌ Could not retrieve download link")
        return

    temp_path = os.path.join(tempfile.gettempdir(), info["name"])

    await status_msg.edit("📥 Downloading file...")

    try:
        # Download using the fast_download link from API
        with requests.get(info["download_link"], stream=True, timeout=60) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            
            with open(temp_path, "wb") as f:
                downloaded = 0
                chunk_size = 1024 * 1024  # 1MB chunks
                
                for chunk in r.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        # Update progress every 10MB
                        if downloaded % (10 * 1024 * 1024) < chunk_size:
                            progress = (downloaded / total_size * 100) if total_size > 0 else 0
                            try:
                                await status_msg.edit(
                                    f"📥 Downloading: {progress:.1f}%\n"
                                    f"📦 {get_size(downloaded)} / {info['size_str']}"
                                )
                            except:
                                pass

        await status_msg.edit("📤 Uploading to Telegram...")

        caption = (
            f"📄 **File Name:** `{info['name']}`\n"
            f"📦 **File Size:** {info['size_str']}\n"
            f"🔗 **Source:** [TeraBox Link]({url})\n\n"
            f"⚡ Powered by @MrMNTG"
        )

        # Upload to channel if configured
        if CHANNEL.ID:
            await client.send_document(
                chat_id=CHANNEL.ID,
                document=temp_path,
                caption=caption,
                file_name=info["name"]
            )

        # Upload to user with auto-delete
        sent_msg = await client.send_document(
            chat_id=message.chat.id,
            document=temp_path,
            caption=caption,
            file_name=info["name"],
            protect_content=True
        )

        await status_msg.delete()
        await message.reply("✅ File uploaded successfully!\n⏰ Will be auto-deleted in 12 hours.")
        
        # Auto-delete after 12 hours
        await asyncio.sleep(43200)
        try:
            await sent_msg.delete()
        except Exception:
            pass

    except requests.RequestException as e:
        await status_msg.edit(f"❌ Download failed:\n`{str(e)}`")
    except Exception as e:
        await status_msg.edit(f"❌ Upload failed:\n`{str(e)}`")
    finally:
        # Cleanup temp file
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass
