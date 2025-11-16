"""Startup initialization utilities."""
import logging
from datetime import datetime, timezone
from database import ImportLog, SessionLocal

logger = logging.getLogger(__name__)


def clear_in_progress_imports():
    """Mark any in-progress imports as error (they were interrupted by server restart)."""
    db = SessionLocal()
    try:
        running_imports = db.query(ImportLog).filter(ImportLog.status == "running").all()
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

