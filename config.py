"""Configuration settings for the application."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory
BASE_DIR = Path(__file__).parent

# Load environment variables from .env file
env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=env_path)

# Database
DATABASE_PATH = BASE_DIR / "data" / "vector_infinity.db"

# Plugins directory
PLUGINS_DIR = BASE_DIR / "plugins"

# Logs directory
LOGS_DIR = BASE_DIR / "logs"

# Web server
# Default to port 5000 if behind Nginx reverse proxy, or 80 if running directly
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", "5000"))  # Changed to 5000 for Nginx reverse proxy

# Scheduler
SCHEDULER_TIMEZONE = os.getenv("TZ", "UTC")
DAILY_IMPORT_TIME = os.getenv("DAILY_IMPORT_TIME", "02:00")  # 2 AM

# OpenAI Vector Store (optional)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Secret key for session management
SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret-key-in-production")

# User-specific directories
USER_DATA_DIR = BASE_DIR / "data" / "users"

# Base URL for OAuth redirects (optional, will auto-detect if not set)
# Set this if you're having redirect URI mismatch issues
# Example: "https://vectorinfinity.com" or "https://your-domain.com"
BASE_URL = os.getenv("BASE_URL", "")

# Create necessary directories
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

