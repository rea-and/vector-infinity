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

# Vector Database (optional - only needed if using vector search)
VECTOR_DB_PATH = BASE_DIR / "data" / "chroma_db"
EMBEDDING_MODEL = "text-embedding-3-small"  # OpenAI embedding model (only needed if using vector DB)

# Plugins directory
PLUGINS_DIR = BASE_DIR / "plugins"

# Logs directory
LOGS_DIR = BASE_DIR / "logs"

# OpenAI API (optional - only needed if using vector DB for embeddings)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = "gpt-5"  # Not used in current architecture (kept for potential future use)

# Web server
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", "5000"))

# Scheduler
SCHEDULER_TIMEZONE = os.getenv("TZ", "UTC")
DAILY_IMPORT_TIME = os.getenv("DAILY_IMPORT_TIME", "02:00")  # 2 AM

# Create necessary directories
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
# VECTOR_DB_PATH is created on demand if vector DB is used
LOGS_DIR.mkdir(parents=True, exist_ok=True)
PLUGINS_DIR.mkdir(parents=True, exist_ok=True)

