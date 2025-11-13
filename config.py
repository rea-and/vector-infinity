"""Configuration settings for the application."""
import os
from pathlib import Path

# Base directory
BASE_DIR = Path(__file__).parent

# Database
DATABASE_PATH = BASE_DIR / "data" / "vector_infinity.db"

# Vector Database
VECTOR_DB_PATH = BASE_DIR / "data" / "chroma_db"
EMBEDDING_MODEL = "text-embedding-3-small"  # OpenAI embedding model (smaller, cheaper, good quality)

# Plugins directory
PLUGINS_DIR = BASE_DIR / "plugins"

# Logs directory
LOGS_DIR = BASE_DIR / "logs"

# OpenAI API
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = "gpt-5"  # GPT-5 model

# Web server
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", "5000"))

# Scheduler
SCHEDULER_TIMEZONE = os.getenv("TZ", "UTC")
DAILY_IMPORT_TIME = os.getenv("DAILY_IMPORT_TIME", "02:00")  # 2 AM

# Create necessary directories
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
VECTOR_DB_PATH.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
PLUGINS_DIR.mkdir(parents=True, exist_ok=True)

