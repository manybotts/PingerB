import os
import time
import logging
import requests
from telegram import Update, ForceReply
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackContext,
)
from pymongo import MongoClient, errors

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


# --- Helper Functions ---

def ping_single_app(url: str) -> tuple[bool, int | None]:
    """Pings a single URL and returns (success, status_code)."""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        return True, response.status_code
    except requests.exceptions.RequestException:
        return False, None

# --- Command Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    await update.message.reply_html(
        rf"Hi {user.mention_html()}! I'm a Koyeb app pinger bot. "
        rf"Use /add <url> to add an app, /list to see added apps, "
        rf"and /remove <url> to remove an app.",
        reply_markup=ForceReply(selective=True),
    )

async def add_app(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Adds an app URL to the database."""
    try:
        app_url = context.args[0]  # Get the URL from the command arguments
        if not app_url.startswith("http"):
            app_url = "https://" + app_url  # Assume https if no protocol
        #Test if url is valid.
        is_up, status_code = ping_single_app(app_url)
        if not is_up:
            raise ValueError("Invalid URL or app is down.")

        apps_collection.insert_one({"url": app_url})
        await update.message.reply_text(f"App '{app_url}' added successfully.")

    except IndexError:
        await update.message.reply_text("Please provide a URL. Usage: /add <url>")
    except errors.DuplicateKeyError:
        await update.message.reply_text(f"App '{app_url}' is already in the list.")
    except ValueError as e:
        await update.message.reply_text(str(e))

    except Exception as e:
        await update.message.reply_text(f"An error occurred: {e}")
        logger.error(f"Error in add_app: {e}")



async def remove_app(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Removes an app URL from the database."""
    try:
        app_url = context.args[0]
        if not app_url.startswith("http"):
            app_url = "https://" + app_url
        result = apps_collection.delete_one({"url": app_url})
        if result.deleted_count == 0:
            await update.message.reply_text(f"App '{app_url}' not found.")
        else:
            await update.message.reply_text(f"App '{app_url}' removed successfully.")
    except IndexError:
        await update.message.reply_text("Please provide a URL. Usage: /remove <url>")
    except Exception as e:
        await update.message.reply_text(f"An error occurred: {e}")
        logger.error(f"Error in remove_app: {e}")


async def list_apps(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lists all currently tracked app URLs."""
    try:
        apps = list(apps_collection.find({}, {"_id": 0, "url": 1}))
        if not apps:
            await update.message.reply_text("No apps are currently being tracked.")
            return

        app_list_str = "\n".join([app["url"] for app in apps])
        await update.message.reply_text(f"Currently tracked apps:\n{app_list_str}")
    except Exception as e:
        await update.message.reply_text(f"An error occurred: {e}")
        logger.error(f"Error in list_apps: {e}")



async def ping_all_apps(context: CallbackContext) -> None:
    """Pings all tracked apps and sends status updates to the admin."""
    try:
        apps = list(apps_collection.find({}, {"_id": 0, "url": 1}))
        for app_doc in apps:
            app_url = app_doc["url"]
            is_up, status_code = ping_single_app(app_url)
            if is_up:
                message = f"✅ App '{app_url}' is UP (Status: {status_code})"
            else:
                message = f"❌ App '{app_url}' is DOWN!"
            await context.bot.send_message(chat_id=context.job.chat_id, text=message) #send to the user who scheduled.
    except Exception as e:
        logger.error(f"Error in ping_all_apps: {e}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    await update.message.reply_text(help_text)

async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Schedules (or reschedules) periodic pings."""
    chat_id = update.effective_message.chat_id

    try:
        # Get the interval from the command arguments
        interval_minutes = int(context.args[0])
        if interval_minutes <= 0:
            raise ValueError("Interval must be a positive number.")
        interval_seconds = interval_minutes * 60

        # Remove existing jobs for the same chat ID
        context.job_queue.remove_job_if_exists(str(chat_id))

        # Schedule the new job
        context.job_queue.run_repeating(
            ping_all_apps, interval=interval_seconds, first=0, chat_id=chat_id, name=str(chat_id)
        )
        await update.message.reply_text(f"Scheduled pings every {interval_minutes} minutes.")

    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /ping <interval_minutes>")

    except Exception as e:
        await update.message.reply_text("An error occured")
        logger.error(f"Error at ping_command {e}")
# --- Main Application Setup ---

def main() -> None:
    """Start the bot."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN environment variable not set!")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Register command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add", add_app))
    application.add_handler(CommandHandler("remove", remove_app))
    application.add_handler(CommandHandler("list", list_apps))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("ping", ping_command))
    # Run the bot
    application.run_polling()

if __name__ == "__main__":
    main()
