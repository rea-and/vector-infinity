"""Data importer that runs plugins and stores data."""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from database import ImportLog, DataItem, SessionLocal
from plugin_loader import PluginLoader
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DataImporter:
    """Handles importing data from plugins."""
    
    def __init__(self):
        self.plugin_loader = PluginLoader()
    
    def import_from_plugin(self, plugin_name: str) -> ImportLog:
        """
        Import data from a specific plugin.
        
        Returns:
            ImportLog object with the result
        """
        db = SessionLocal()
        plugin = self.plugin_loader.get_plugin(plugin_name)
        
        if not plugin:
            log_entry = ImportLog(
                plugin_name=plugin_name,
                status="error",
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                error_message=f"Plugin {plugin_name} not found or not enabled"
            )
            db.add(log_entry)
            db.commit()
            db.close()
            return log_entry
        
        # Create log entry
        log_entry = ImportLog(
            plugin_name=plugin_name,
            status="running",
            started_at=datetime.now(timezone.utc)
        )
        db.add(log_entry)
        db.commit()
        
        try:
            # Fetch data from plugin
            logger.info(f"Fetching data from plugin: {plugin_name}")
            data_items = plugin.fetch_data()
            
            records_imported = 0
            for item_data in data_items:
                # Check if item already exists
                existing = db.query(DataItem).filter_by(
                    plugin_name=plugin_name,
                    source_id=item_data.get("source_id")
                ).first()
                
                if existing:
                    # Update existing item
                    existing.title = item_data.get("title")
                    existing.content = item_data.get("content")
                    existing.item_metadata = item_data.get("metadata", {})
                    existing.updated_at = datetime.now(timezone.utc)
                    if item_data.get("source_timestamp"):
                        existing.source_timestamp = item_data.get("source_timestamp")
                else:
                    # Create new item
                    new_item = DataItem(
                        plugin_name=plugin_name,
                        source_id=item_data.get("source_id"),
                        item_type=item_data.get("item_type", "unknown"),
                        title=item_data.get("title"),
                        content=item_data.get("content"),
                        item_metadata=item_data.get("metadata", {}),
                        source_timestamp=item_data.get("source_timestamp")
                    )
                    db.add(new_item)
                    records_imported += 1
            
            db.commit()
            
            # Update log entry
            log_entry.status = "success"
            log_entry.completed_at = datetime.now(timezone.utc)
            log_entry.records_imported = records_imported
            db.commit()
            
            logger.info(f"Successfully imported {records_imported} items from {plugin_name}")
            
        except Exception as e:
            logger.error(f"Error importing from {plugin_name}: {e}", exc_info=True)
            log_entry.status = "error"
            log_entry.completed_at = datetime.now(timezone.utc)
            log_entry.error_message = str(e)
            db.commit()
        
        finally:
            db.close()
        
        return log_entry
    
    def import_all(self) -> dict:
        """Import data from all enabled plugins."""
        results = {}
        plugins = self.plugin_loader.get_all_plugins()
        
        for plugin_name in plugins:
            results[plugin_name] = self.import_from_plugin(plugin_name)
        
        return results

