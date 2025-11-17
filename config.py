"""
Configuration module for Terabox Downloader Bot
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Telegram Bot Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")

# MongoDB Configuration
MONGODB_URL = os.getenv("MONGODB_URL")
if not MONGODB_URL:
    raise ValueError("MONGODB_URL environment variable is required")

MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "terabox_bot")

# Admin Configuration (for sending restart notifications)
ADMIN_ID = os.getenv("ADMIN_ID")

# Store Channel Configuration (for archiving all downloads)
STORE_CHANNEL = os.getenv("STORE_CHANNEL", "-1003292407667")

# API Configuration
TERABOX_API = "https://iteraplay.com/api/play.php?url={url}&key=iTeraPlay2025"

# Download Configuration
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "./downloads")
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", 2147483648))  # 2GB default
TIMEOUT = int(os.getenv("TIMEOUT", 30))

# File size constants
MAX_TELEGRAM_FILE_SIZE_MB = 2000  # Telegram bot API limit
MIN_VALID_FILE_SIZE_BYTES = 1000  # Files smaller than this are likely errors
HTTP_CHUNK_SIZE = 65536  # 64KB chunks for HTTP downloads

# Bot Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")
