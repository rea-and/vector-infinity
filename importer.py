"""Data importer that runs plugins and stores data."""
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from database import ImportLog, DataItem, SessionLocal
from plugin_loader import PluginLoader
from vector_db import get_vector_db
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DataImporter:
    """Handles importing data from plugins."""
    
    def __init__(self):
        self.plugin_loader = PluginLoader()
        self.vector_db = get_vector_db()
    
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
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
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
            started_at=datetime.utcnow()
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
                
                # Prepare text for embedding (combine title and content)
                title = item_data.get("title", "")
                content = item_data.get("content", "")
                text_for_embedding = f"{title}\n\n{content}".strip()
                
                if existing:
                    # Update existing item
                    existing.title = item_data.get("title")
                    existing.content = item_data.get("content")
                    existing.item_metadata = item_data.get("metadata", {})
                    existing.updated_at = datetime.utcnow()
                    if item_data.get("source_timestamp"):
                        existing.source_timestamp = item_data.get("source_timestamp")
                    
                    # Update in vector DB
                    if text_for_embedding:
                        vector_metadata = {
                            "plugin_name": plugin_name,
                            "item_type": existing.item_type,
                            "source_id": existing.source_id,
                            "title": title[:200] if title else "",  # Limit for metadata
                        }
                        self.vector_db.update_item(
                            str(existing.id),
                            text_for_embedding,
                            vector_metadata
                        )
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
                    db.flush()  # Flush to get the ID
                    
                    # Add to vector DB
                    if text_for_embedding:
                        vector_metadata = {
                            "plugin_name": plugin_name,
                            "item_type": new_item.item_type,
                            "source_id": new_item.source_id,
                            "title": title[:200] if title else "",
                        }
                        self.vector_db.add_item(
                            str(new_item.id),
                            text_for_embedding,
                            vector_metadata
                        )
                    
                    records_imported += 1
            
            db.commit()
            
            # Update log entry
            log_entry.status = "success"
            log_entry.completed_at = datetime.utcnow()
            log_entry.records_imported = records_imported
            db.commit()
            
            logger.info(f"Successfully imported {records_imported} items from {plugin_name}")
            
        except Exception as e:
            logger.error(f"Error importing from {plugin_name}: {e}", exc_info=True)
            log_entry.status = "error"
            log_entry.completed_at = datetime.utcnow()
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

