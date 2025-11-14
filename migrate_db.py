"""Database migration script to add progress tracking columns."""
from database import engine, ImportLog
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate_database():
    """Add progress tracking columns to import_logs table if they don't exist."""
    with engine.connect() as conn:
        # Check if columns exist
        result = conn.execute(text("PRAGMA table_info(import_logs)"))
        columns = [row[1] for row in result]
        
        # Add progress_current if it doesn't exist
        if 'progress_current' not in columns:
            logger.info("Adding progress_current column...")
            conn.execute(text("ALTER TABLE import_logs ADD COLUMN progress_current INTEGER DEFAULT 0"))
            conn.commit()
            logger.info("✓ Added progress_current column")
        else:
            logger.info("progress_current column already exists")
        
        # Add progress_total if it doesn't exist
        if 'progress_total' not in columns:
            logger.info("Adding progress_total column...")
            conn.execute(text("ALTER TABLE import_logs ADD COLUMN progress_total INTEGER DEFAULT 0"))
            conn.commit()
            logger.info("✓ Added progress_total column")
        else:
            logger.info("progress_total column already exists")
        
        # Add progress_message if it doesn't exist
        if 'progress_message' not in columns:
            logger.info("Adding progress_message column...")
            conn.execute(text("ALTER TABLE import_logs ADD COLUMN progress_message VARCHAR(500)"))
            conn.commit()
            logger.info("✓ Added progress_message column")
        else:
            logger.info("progress_message column already exists")
        
        logger.info("Database migration completed successfully!")


if __name__ == "__main__":
    migrate_database()

