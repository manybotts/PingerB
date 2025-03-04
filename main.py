import os
import time
import logging
import asyncio
import requests
from pyrogram import Client, filters
from pyrogram.types import Message, ForceReply
from pymongo import MongoClient, errors
from typing import Union, Tuple  # <--- IMPORTANT: Import Union and Tuple

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# MongoDB configuration (from environment variables)
MONGO_URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("MONGODB_DB_NAME", "koyeb")
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
apps_collection = db["apps"]

# Ensure unique index
apps_collection.create_index("url", unique=True)

# Telegram Bot Token (from environment variable)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
API_ID = os.environ.get("API_ID")  # Get from my.telegram.org
API_HASH = os.environ.get("API_HASH") # Get from my.telegram.org

# --- Helper Functions ---

def ping_single_app(url: str) -> Tuple[bool, Union[int, None]]: #Corrected type hint
    """Pings a single URL and returns (success, status_code)."""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        return True, response.status_code
    except requests.exceptions.RequestException:
        return False, None

# --- Pyrogram Client Setup ---
app = Client(
    "koyeb_pinger_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=TELEGRAM_BOT_TOKEN,
)

# --- Command Handlers ---
@app.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    """Send a message when the command /start is issued."""
    await message.reply_text(
        f"Hi {message.from_user.mention}! I'm a Koyeb app pinger bot. "
        f"Use /add <url> to add an app, /list to see added apps, "
        f"and /remove <url> to remove an app."
        #reply_markup=ForceReply(selective=True) #Removed force reply.
    )

@app.on_message(filters.command("add"))
async def add_app(client: Client, message: Message):
    """Adds an app URL to the database."""
    try:
        app_url = message.command[1]  # Get the URL from the command
        if not app_url.startswith("http"):
            app_url = "https://" + app_url
        is_up, status_code = ping_single_app(app_url)
        if not is_up:
            raise ValueError("Invalid URL or app is down.")

        apps_collection.insert_one({"url": app_url})
        await message.reply_text(f"App '{app_url}' added successfully.")

    except IndexError:
        await message.reply_text("Please provide a URL. Usage: /add <url>")
    except errors.DuplicateKeyError:
        await message.reply_text(f"App '{app_url}' is already in the list.")
    except ValueError as e:
         await message.reply_text(str(e))
    except Exception as e:
        await message.reply_text(f"An error occurred: {e}")
        logger.error(f"Error in add_app: {e}")

@app.on_message(filters.command("remove"))
async def remove_app(client: Client, message: Message):
    """Removes an app URL from the database."""
    try:
        app_url = message.command[1]
        if not app_url.startswith("http"):
          app_url = "https://" + app_url
        result = apps_collection.delete_one({"url": app_url})
        if result.deleted_count == 0:
            await message.reply_text(f"App '{app_url}' not found.")
        else:
            await message.reply_text(f"App '{app_url}' removed successfully.")
    except IndexError:
        await message.reply_text("Please provide a URL. Usage: /remove <url>")
    except Exception as e:
        await message.reply_text(f"An error occurred: {e}")
        logger.error(f"Error in remove_app: {e}")

@app.on_message(filters.command("list"))
async def list_apps(client: Client, message: Message):
    """Lists all currently tracked app URLs."""
    try:
        apps = list(apps_collection.find({}, {"_id": 0, "url": 1}))
        if not apps:
            await message.reply_text("No apps are currently being tracked.")
            return

        app_list_str = "\n".join([app["url"] for app in apps])
        await message.reply_text(f"Currently tracked apps:\n{app_list_str}")
    except Exception as e:
        await message.reply_text(f"An error occurred: {e}")
        logger.error(f"Error in list_apps: {e}")


@app.on_message(filters.command("help"))
async def help_command(client: Client, message: Message):
    """Displays help information."""
    help_text = (
        "Available commands:\n"
        "/start - Start the bot\n"
        "/add <url> - Add a Koyeb app URL to be monitored\n"
        "/remove <url> - Remove a Koyeb app URL\n"
        "/list - List all monitored app URLs\n"
        "/help - Show this help message\n"
        "/ping <interval_minutes> - Schedule periodic pings (e.g., /ping 10)"
    )
    await message.reply_text(help_text)

@app.on_message(filters.command("ping"))
async def ping_command(client: Client, message: Message):
    """Schedules (or reschedules) periodic pings."""
    chat_id = message.chat.id

    try:
        interval_minutes = int(message.command[1])
        if interval_minutes <= 0:
          raise ValueError("Interval must be a positive number.")
        interval_seconds = interval_minutes * 60

        # Cancel existing task if it exists
        if chat_id in ping_tasks:
            ping_tasks[chat_id].cancel()
            try:
                await ping_tasks[chat_id]  # Ensure task is cancelled
            except asyncio.CancelledError:
                pass

        #Schedule the new task.
        task = asyncio.create_task(ping_all_apps(chat_id, interval_seconds))
        ping_tasks[chat_id] = task
        await message.reply_text(f"Scheduled pings every {interval_minutes} minutes.")
    except (IndexError, ValueError):
        await message.reply_text("Usage: /ping <interval_minutes>")
    except Exception as e:
        await message.reply_text("An error occurred.")
        logger.error(f"Error at ping_command: {e}")


ping_tasks = {}  # Dictionary to store ping tasks, keyed by chat ID

async def ping_all_apps(chat_id: int, interval: int):
    """Pings all tracked apps and sends status updates."""
    while True:  # Run in an infinite loop
        try:
            apps = list(apps_collection.find({}, {"_id": 0, "url": 1}))
            for app_doc in apps:
                app_url = app_doc["url"]
                is_up, status_code = ping_single_app(app_url)
                if is_up:
                    message_text = f"✅ App '{app_url}' is UP (Status: {status_code})"
                else:
                    message_text = f"❌ App '{app_url}' is DOWN!"
                await app.send_message(chat_id=chat_id, text=message_text)
            await asyncio.sleep(interval)  # Wait for the specified interval
        except Exception as e:
            logger.error(f"Error in ping_all_apps: {e}")
            await asyncio.sleep(interval)  #Even if error occurs. wait.



# --- Main Application Start ---

if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or not API_ID or not API_HASH:
        logger.error("TELEGRAM_BOT_TOKEN, API_ID, and API_HASH environment variables must be set!")
    else:
        app.run()
