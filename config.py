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

# Available GPT models for assistant (comma-separated list)
# Format: "model1,model2,model3" or "model1:Display Name 1,model2:Display Name 2"
# If no display name is provided, the model name will be used
# Note: Display names can contain commas - they will be preserved
# Example: "gpt-4o-mini:GPT-4o Mini (Fast, Cost-Effective),gpt-4o:GPT-4o (Balanced)"
AVAILABLE_MODELS_STR = os.getenv(
    "AVAILABLE_MODELS",
    "gpt-4o-mini:GPT-4o Mini (Fast, Cost-Effective),gpt-4o:GPT-4o (Balanced),gpt-4-turbo:GPT-4 Turbo (High Performance),gpt-4:GPT-4 (Legacy),gpt-3.5-turbo:GPT-3.5 Turbo (Fastest, Lowest Cost)"
)

# Parse available models into a list of model names and a dict of display names
# Handle commas in display names by identifying model entries by their prefixes
AVAILABLE_MODELS = []
MODEL_DISPLAY_NAMES = {}
DEFAULT_MODEL = "gpt-4o-mini"

if AVAILABLE_MODELS_STR:
    # Split by comma, then reconstruct entries by grouping items
    # Model entries typically start with patterns like "gpt-", "o1-", "claude-", etc.
    parts = [p.strip() for p in AVAILABLE_MODELS_STR.split(",")]
    
    current_entry = None
    for part in parts:
        if not part:
            continue
            
        # Check if this part starts a new model entry (starts with model name pattern)
        # Common patterns: gpt-, o1-, claude-, gemini-, etc.
        is_model_start = any(part.startswith(prefix) for prefix in [
            "gpt-", "o1-", "claude-", "gemini-", "llama-", "mistral-", "anthropic-"
        ]) or (":" in part and any(part.split(":")[0].strip().startswith(prefix) for prefix in [
            "gpt-", "o1-", "claude-", "gemini-", "llama-", "mistral-", "anthropic-"
        ]))
        
        if is_model_start:
            # Save previous entry if exists
            if current_entry:
                if ":" in current_entry:
                    model_name, display_name = current_entry.split(":", 1)
                    model_name = model_name.strip()
                    display_name = display_name.strip()
                    AVAILABLE_MODELS.append(model_name)
                    MODEL_DISPLAY_NAMES[model_name] = display_name
                else:
                    AVAILABLE_MODELS.append(current_entry)
                    MODEL_DISPLAY_NAMES[current_entry] = current_entry
            
            # Start new entry
            current_entry = part
        else:
            # This is a continuation of the previous entry (part of display name)
            if current_entry:
                current_entry += ", " + part
            else:
                # No current entry, treat as standalone (shouldn't happen but handle gracefully)
                current_entry = part
    
    # Don't forget the last entry
    if current_entry:
        if ":" in current_entry:
            model_name, display_name = current_entry.split(":", 1)
            model_name = model_name.strip()
            display_name = display_name.strip()
            AVAILABLE_MODELS.append(model_name)
            MODEL_DISPLAY_NAMES[model_name] = display_name
        else:
            AVAILABLE_MODELS.append(current_entry)
            MODEL_DISPLAY_NAMES[current_entry] = current_entry

# Ensure default model is in the list
if DEFAULT_MODEL not in AVAILABLE_MODELS:
    AVAILABLE_MODELS.insert(0, DEFAULT_MODEL)
    MODEL_DISPLAY_NAMES[DEFAULT_MODEL] = DEFAULT_MODEL

# Create necessary directories
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

