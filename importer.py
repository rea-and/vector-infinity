"""Data importer that runs plugins and stores data."""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from database import ImportLog, DataItem, SessionLocal
from plugin_loader import PluginLoader
import logging
import threading

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ImportLogResult:
    """Simple result object to avoid SQLAlchemy DetachedInstanceError."""
    def __init__(self, data):
        self.id = data["id"]
        self.plugin_name = data["plugin_name"]
        self.status = data["status"]
        self.started_at = data["started_at"]
        self.completed_at = data["completed_at"]
        self.records_imported = data["records_imported"]
        self.error_message = data.get("error_message")
        self.progress_current = data.get("progress_current", 0)
        self.progress_total = data.get("progress_total", 0)
        self.progress_message = data.get("progress_message", "")


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
            # Extract values before closing session
            result = {
                "id": log_entry.id,
                "plugin_name": log_entry.plugin_name,
                "status": log_entry.status,
                "started_at": log_entry.started_at,
                "completed_at": log_entry.completed_at,
                "records_imported": log_entry.records_imported,
                "error_message": log_entry.error_message,
                "progress_current": 0,
                "progress_total": 0,
                "progress_message": ""
            }
            db.close()
            return ImportLogResult(result)
        
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
            
            # Update progress: fetching data
            log_entry.progress_message = "Fetching data from source..."
            db.commit()
            
            data_items = plugin.fetch_data()
            
            # Update progress: processing items
            total_items = len(data_items)
            log_entry.progress_total = total_items
            log_entry.progress_current = 0
            log_entry.progress_message = f"Processing {total_items} items..."
            db.commit()
            
            records_imported = 0
            items_to_embed = []  # Collect items for embedding generation
            
            for idx, item_data in enumerate(data_items):
                # Update progress every 10 items or on last item
                if idx % 10 == 0 or idx == len(data_items) - 1:
                    log_entry.progress_current = idx + 1
                    log_entry.progress_message = f"Processing item {idx + 1} of {total_items}..."
                    db.commit()
                # Check if item already exists
                existing = db.query(DataItem).filter_by(
                    plugin_name=plugin_name,
                    source_id=item_data.get("source_id")
                ).first()
                
                # Prepare text for embedding
                text_parts = []
                if item_data.get("title"):
                    text_parts.append(f"Subject: {item_data['title']}")
                if item_data.get("metadata", {}).get("from"):
                    text_parts.append(f"From: {item_data['metadata']['from']}")
                if item_data.get("content"):
                    text_parts.append(item_data["content"])
                text_for_embedding = "\n".join(text_parts)
                
                if existing:
                    # Update existing item
                    existing.title = item_data.get("title")
                    existing.content = item_data.get("content")
                    existing.item_metadata = item_data.get("metadata", {})
                    existing.updated_at = datetime.now(timezone.utc)
                    if item_data.get("source_timestamp"):
                        existing.source_timestamp = item_data.get("source_timestamp")
                    # Re-generate embedding if content changed
                    if text_for_embedding:
                        items_to_embed.append((existing, text_for_embedding))
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
                    if text_for_embedding:
                        items_to_embed.append((new_item, text_for_embedding))
                
                # Collect item for vector store sync
            
            db.commit()
            
            # Generate embeddings for items
            if items_to_embed:
                log_entry.progress_message = f"Generating embeddings for {len(items_to_embed)} items..."
                db.commit()
                try:
                    from embedding_service import EmbeddingService
                    embedding_service = EmbeddingService()
                    
                    # Generate embeddings in batches
                    texts = [text for _, text in items_to_embed]
                    embeddings = embedding_service.generate_embeddings_batch(texts)
                    
                    # Store embeddings
                    for (item, _), embedding in zip(items_to_embed, embeddings):
                        if embedding:
                            item.embedding = embedding_service.embedding_to_bytes(embedding)
                    
                    db.commit()
                    logger.info(f"Generated {sum(1 for e in embeddings if e)} embeddings for {plugin_name}")
                except Exception as e:
                    logger.warning(f"Failed to generate embeddings (this is optional): {e}")
            
            db.commit()
            
            # Update log entry
            log_entry.status = "success"
            log_entry.completed_at = datetime.now(timezone.utc)
            log_entry.records_imported = records_imported
            log_entry.progress_current = log_entry.progress_total
            log_entry.progress_message = f"Completed: {records_imported} records imported"
            db.commit()
            
            logger.info(f"Successfully imported {records_imported} items from {plugin_name}")
            
        except Exception as e:
            logger.error(f"Error importing from {plugin_name}: {e}", exc_info=True)
            log_entry.status = "error"
            log_entry.completed_at = datetime.now(timezone.utc)
            log_entry.error_message = str(e)
            log_entry.progress_message = f"Error: {str(e)[:200]}"
            db.commit()
        
        finally:
            # Extract values before closing session to avoid DetachedInstanceError
            result = {
                "id": log_entry.id,
                "plugin_name": log_entry.plugin_name,
                "status": log_entry.status,
                "started_at": log_entry.started_at,
                "completed_at": log_entry.completed_at,
                "records_imported": log_entry.records_imported,
                "error_message": log_entry.error_message,
                "progress_current": log_entry.progress_current or 0,
                "progress_total": log_entry.progress_total or 0,
                "progress_message": log_entry.progress_message or ""
            }
            db.close()
        
        return ImportLogResult(result)
    
    def import_all(self) -> dict:
        """Import data from all enabled plugins."""
        results = {}
        plugins = self.plugin_loader.get_all_plugins()
        
        for plugin_name in plugins:
            results[plugin_name] = self.import_from_plugin(plugin_name)
        
        return results
    
    def import_from_plugin_async(self, plugin_name: str, log_id: int):
        """Run import in a background thread."""
        def run_import():
            db = SessionLocal()
            try:
                log_entry = db.query(ImportLog).filter_by(id=log_id).first()
                if not log_entry:
                    return
                
                # Run the actual import (reuse existing logic)
                # We need to update the log_entry in this thread
                plugin = self.plugin_loader.get_plugin(plugin_name)
                if not plugin:
                    log_entry.status = "error"
                    log_entry.completed_at = datetime.now(timezone.utc)
                    log_entry.error_message = f"Plugin {plugin_name} not found or not enabled"
                    db.commit()
                    return
                
                try:
                    log_entry.progress_message = "Fetching data from source..."
                    db.commit()
                    
                    data_items = plugin.fetch_data()
                    
                    total_items = len(data_items)
                    log_entry.progress_total = total_items
                    log_entry.progress_current = 0
                    log_entry.progress_message = f"Processing {total_items} items..."
                    db.commit()
                    
                    records_imported = 0
                    items_to_embed = []
                    
                    for idx, item_data in enumerate(data_items):
                        if idx % 10 == 0 or idx == len(data_items) - 1:
                            log_entry.progress_current = idx + 1
                            log_entry.progress_message = f"Processing item {idx + 1} of {total_items}..."
                            db.commit()
                        
                        existing = db.query(DataItem).filter_by(
                            plugin_name=plugin_name,
                            source_id=item_data.get("source_id")
                        ).first()
                        
                        # Prepare text for embedding (different formats for different item types)
                        text_parts = []
                        item_type = item_data.get("item_type", "")
                        
                        if item_type == "whatsapp_message":
                            # Format for WhatsApp messages
                            if item_data.get("metadata", {}).get("sender"):
                                text_parts.append(f"From: {item_data['metadata']['sender']}")
                            if item_data.get("content"):
                                text_parts.append(item_data["content"])
                        else:
                            # Format for emails and other items
                            if item_data.get("title"):
                                text_parts.append(f"Subject: {item_data['title']}")
                            if item_data.get("metadata", {}).get("from"):
                                text_parts.append(f"From: {item_data['metadata']['from']}")
                            if item_data.get("content"):
                                text_parts.append(item_data["content"])
                        
                        text_for_embedding = "\n".join(text_parts)
                        
                        if existing:
                            existing.title = item_data.get("title")
                            existing.content = item_data.get("content")
                            existing.item_metadata = item_data.get("metadata", {})
                            existing.updated_at = datetime.now(timezone.utc)
                            if item_data.get("source_timestamp"):
                                existing.source_timestamp = item_data.get("source_timestamp")
                            # Re-generate embedding if content changed
                            if text_for_embedding:
                                items_to_embed.append((existing, text_for_embedding))
                        else:
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
                            if text_for_embedding:
                                items_to_embed.append((new_item, text_for_embedding))
                        
                    
                    db.commit()
                    
                    # Generate embeddings for items
                    if items_to_embed:
                        log_entry.progress_message = f"Generating embeddings for {len(items_to_embed)} items..."
                        db.commit()
                        try:
                            from embedding_service import EmbeddingService
                            embedding_service = EmbeddingService()
                            
                            # Generate embeddings in batches
                            texts = [text for _, text in items_to_embed]
                            embeddings = embedding_service.generate_embeddings_batch(texts)
                            
                            # Store embeddings
                            for (item, _), embedding in zip(items_to_embed, embeddings):
                                if embedding:
                                    item.embedding = embedding_service.embedding_to_bytes(embedding)
                            
                            db.commit()
                            logger.info(f"Generated {sum(1 for e in embeddings if e)} embeddings for {plugin_name}")
                        except Exception as e:
                            logger.warning(f"Failed to generate embeddings (this is optional): {e}")
                    
                    db.commit()
                    
                    log_entry.status = "success"
                    log_entry.completed_at = datetime.now(timezone.utc)
                    log_entry.records_imported = records_imported
                    log_entry.progress_current = log_entry.progress_total
                    log_entry.progress_message = f"Completed: {records_imported} records imported"
                    db.commit()
                    
                    logger.info(f"Successfully imported {records_imported} items from {plugin_name}")
                    
                except Exception as e:
                    logger.error(f"Error importing from {plugin_name}: {e}", exc_info=True)
                    log_entry.status = "error"
                    log_entry.completed_at = datetime.now(timezone.utc)
                    log_entry.error_message = str(e)
                    log_entry.progress_message = f"Error: {str(e)[:200]}"
                    db.commit()
            finally:
                db.close()
        
        thread = threading.Thread(target=run_import, daemon=True)
        thread.start()

