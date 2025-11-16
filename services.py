"""Shared service instances for the application."""
import logging
from importer import DataImporter
from scheduler import ImportScheduler
from plugin_loader import PluginLoader
from utils.startup import clear_in_progress_imports
from database import init_db

logger = logging.getLogger(__name__)

# Initialize database
init_db()

# Run migration to add multi-user support if needed
try:
    from migrate_to_multi_user import migrate_database
    migrate_database()
except Exception as e:
    logger.warning(f"Migration check failed (this is OK if database is already migrated): {e}")

# Clear any in-progress imports on startup
clear_in_progress_imports()

# Initialize services
importer = DataImporter()
plugin_loader = PluginLoader()
scheduler = ImportScheduler()
scheduler.start()

# OAuth flows storage (in production, use Redis or similar)
oauth_flows = {}

