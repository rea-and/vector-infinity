"""Startup initialization utilities."""
import logging
from datetime import datetime, timezone
from database import ImportLog, SessionLocal

logger = logging.getLogger(__name__)


def clear_in_progress_imports():
    """Mark any in-progress imports as error (they were interrupted by server restart)."""
    db = SessionLocal()
    try:
        # Check if user_id column exists (for backward compatibility during migration)
        try:
            # Try to query with user_id - if it fails, the column doesn't exist yet
            # and we'll skip this step (migration will handle it)
            running_imports = db.query(ImportLog).filter(ImportLog.status == "running").all()
        except Exception as e:
            if "user_id" in str(e):
                # Column doesn't exist yet, skip this step
                logger.info("Skipping clear_in_progress_imports - database migration needed")
                return
            raise
        if running_imports:
            for log_entry in running_imports:
                log_entry.status = "error"
                log_entry.error_message = "Import interrupted by server restart"
                log_entry.completed_at = datetime.now(timezone.utc)
            db.commit()
            logger.info(f"Marked {len(running_imports)} in-progress imports as error due to server restart")
    except Exception as e:
        logger.error(f"Error clearing in-progress imports on startup: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

