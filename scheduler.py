"""Scheduler for daily imports."""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import config
from importer import DataImporter
from database import User, SessionLocal
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ImportScheduler:
    """Manages scheduled data imports."""
    
    def __init__(self):
        self.scheduler = BackgroundScheduler(timezone=config.SCHEDULER_TIMEZONE)
        self.importer = DataImporter()
        self._setup_jobs()
    
    def _setup_jobs(self):
        """Set up scheduled jobs."""
        # Parse daily import time
        hour, minute = map(int, config.DAILY_IMPORT_TIME.split(":"))
        
        # Schedule daily import
        self.scheduler.add_job(
            func=self._run_daily_import,
            trigger=CronTrigger(hour=hour, minute=minute),
            id="daily_import",
            name="Daily data import",
            replace_existing=True
        )
        
        logger.info(f"Scheduled daily import at {config.DAILY_IMPORT_TIME}")
    
    def _run_daily_import(self):
        """Run daily import from all plugins for all active users."""
        logger.info("Starting scheduled daily import")
        db = SessionLocal()
        try:
            # Get all active users
            active_users = db.query(User).filter(User.active == 1).all()
            logger.info(f"Found {len(active_users)} active users for daily import")
            
            all_results = {}
            for user in active_users:
                try:
                    logger.info(f"Running daily import for user {user.id} ({user.email})")
                    results = self.importer.import_all(user_id=user.id)
                    all_results[user.id] = results
                    logger.info(f"Daily import completed for user {user.id}. Results: {results}")
                except Exception as e:
                    logger.error(f"Error in daily import for user {user.id}: {e}", exc_info=True)
                    all_results[user.id] = {"error": str(e)}
            
            logger.info(f"Daily import completed for all users. Results: {all_results}")
        except Exception as e:
            logger.error(f"Error in daily import: {e}", exc_info=True)
        finally:
            db.close()
    
    def start(self):
        """Start the scheduler."""
        self.scheduler.start()
        logger.info("Scheduler started")
    
    def stop(self):
        """Stop the scheduler."""
        self.scheduler.shutdown()
        logger.info("Scheduler stopped")

