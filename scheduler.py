"""Scheduler for daily imports."""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import config
from importer import DataImporter
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
        """Run daily import from all plugins."""
        logger.info("Starting scheduled daily import")
        try:
            results = self.importer.import_all()
            logger.info(f"Daily import completed. Results: {results}")
        except Exception as e:
            logger.error(f"Error in daily import: {e}", exc_info=True)
    
    def start(self):
        """Start the scheduler."""
        self.scheduler.start()
        logger.info("Scheduler started")
    
    def stop(self):
        """Stop the scheduler."""
        self.scheduler.shutdown()
        logger.info("Scheduler stopped")

