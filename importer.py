"""Data importer that runs plugins and stores data."""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from database import ImportLog, DataItem, SessionLocal, PluginConfiguration
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
            items_to_upload = []  # Collect items for vector store upload
            
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
                
                if existing:
                    # Skip existing items - only import new ones
                    continue
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
                    # Collect items for vector store upload
                    items_to_upload.append(item_data)
            
            db.commit()
            
            # Upload new items to vector store
            if items_to_upload:
                try:
                    from vector_store_service import VectorStoreService
                    vector_store_service = VectorStoreService()
                    
                    log_entry.progress_message = f"Uploading {len(items_to_upload)} items to vector store..."
                    db.commit()
                    
                    # Upload in batches to avoid overwhelming the API
                    # Increased batch size for better performance
                    batch_size = 500  # Increased from 100 to 500 for faster uploads
                    total_uploaded = 0
                    total_batches = (len(items_to_upload) + batch_size - 1) // batch_size
                    
                    for batch_start in range(0, len(items_to_upload), batch_size):
                        batch_end = min(batch_start + batch_size, len(items_to_upload))
                        batch_items = items_to_upload[batch_start:batch_end]
                        batch_num = batch_start // batch_size + 1
                        
                        log_entry.progress_message = f"Uploading to vector store: batch {batch_num}/{total_batches} ({batch_end}/{len(items_to_upload)} items)..."
                        db.commit()
                        
                        # Only wait for processing on the last batch to ensure data is available
                        # This allows OpenAI to process files in parallel for better performance
                        wait_for_processing = (batch_num == total_batches)
                        success = vector_store_service.upload_data_to_vector_store(plugin_name, batch_items, user_id=user_id, wait_for_processing=wait_for_processing)
                        if success:
                            total_uploaded += len(batch_items)
                            logger.info(f"Uploaded batch {batch_num}/{total_batches} to vector store ({batch_end}/{len(items_to_upload)} items)")
                        else:
                            logger.warning(f"Failed to upload batch {batch_num}/{total_batches} to vector store")
                    
                    logger.info(f"Uploaded {total_uploaded} items to vector store for {plugin_name}")
                    log_entry.progress_message = f"Successfully uploaded {total_uploaded} items to vector store"
                    db.commit()
                except Exception as e:
                    logger.error(f"Failed to upload to vector store: {e}", exc_info=True)
                    log_entry.progress_message = f"Warning: Vector store upload failed: {str(e)[:200]}"
                    db.commit()
            
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
    
    def import_from_plugin_async(self, plugin_name: str, log_id: int, user_id: int, uploaded_file_path: str = None):
        """Run import in a background thread."""
        def run_import():
            db = SessionLocal()
            try:
                log_entry = db.query(ImportLog).filter_by(id=log_id, user_id=user_id).first()
                if not log_entry:
                    return
                
                # Check if plugin is enabled for this user
                plugin_config_db = db.query(PluginConfiguration).filter(
                    PluginConfiguration.user_id == user_id,
                    PluginConfiguration.plugin_name == plugin_name
                ).first()
                
                enabled = False
                if plugin_config_db and plugin_config_db.config_data:
                    enabled = plugin_config_db.config_data.get("enabled", False)
                
                if not enabled:
                    log_entry.status = "error"
                    log_entry.error_message = "Plugin is not enabled. Please enable it first."
                    log_entry.completed_at = datetime.now(timezone.utc)
                    db.commit()
                    logger.warning(f"Import attempted for disabled plugin {plugin_name} (user {user_id})")
                    return
                
                # Run the actual import (reuse existing logic)
                # We need to update the log_entry in this thread
                plugin = self.plugin_loader.get_plugin(plugin_name)
                
                # If plugin not loaded, try to load it manually (for user-specific enabled plugins)
                if not plugin:
                    # Try to load the plugin directly
                    try:
                        import importlib.util
                        import sys
                        from pathlib import Path
                        import config
                        
                        plugin_dir = config.PLUGINS_DIR / plugin_name
                        plugin_file = plugin_dir / "plugin.py"
                        
                        if plugin_file.exists():
                            spec = importlib.util.spec_from_file_location(
                                f"plugins.{plugin_name}.plugin",
                                plugin_file
                            )
                            module = importlib.util.module_from_spec(spec)
                            sys.modules[f"plugins.{plugin_name}.plugin"] = module
                            spec.loader.exec_module(module)
                            
                            if hasattr(module, 'Plugin'):
                                plugin = module.Plugin()
                                logger.info(f"Manually loaded plugin {plugin_name} for import")
                    except Exception as e:
                        logger.error(f"Error manually loading plugin {plugin_name}: {e}", exc_info=True)
                
                if not plugin:
                    log_entry.status = "error"
                    log_entry.error_message = f"Plugin {plugin_name} not found"
                    log_entry.completed_at = datetime.now(timezone.utc)
                    db.commit()
                    return
                
                # Load user-specific plugin configuration from database
                if plugin_name == "github_context":
                    if plugin_config_db and hasattr(plugin, 'set_user_config'):
                        plugin.set_user_config(plugin_config_db.config_data)
                        logger.info(f"Loaded user config for {plugin_name}: token_configured={bool(plugin_config_db.config_data.get('github_token'))}, file_urls={len(plugin_config_db.config_data.get('file_urls', []))}")
                    elif not plugin_config_db:
                        log_entry.status = "error"
                        log_entry.error_message = "Plugin not configured. Please configure it first (GitHub token and file URLs)."
                        log_entry.completed_at = datetime.now(timezone.utc)
                        db.commit()
                        return
                    else:
                        log_entry.status = "error"
                        log_entry.error_message = "Plugin configuration error. Please reconfigure the plugin."
                        log_entry.completed_at = datetime.now(timezone.utc)
                        db.commit()
                        return
                
                # Set file path for whatsapp_angel plugin if provided
                if plugin_name == "whatsapp_angel" and uploaded_file_path:
                    if hasattr(plugin, 'set_uploaded_file'):
                        plugin.set_uploaded_file(str(uploaded_file_path))
                        logger.info(f"Set uploaded file path on plugin in async thread: {uploaded_file_path}")
                    else:
                        log_entry.status = "error"
                        log_entry.error_message = "Plugin does not support file uploads"
                        log_entry.completed_at = datetime.now(timezone.utc)
                        db.commit()
                        return
                
                # Verify file path is set for whatsapp_angel plugin
                if plugin_name == "whatsapp_angel" and hasattr(plugin, 'uploaded_file_path'):
                    if not plugin.uploaded_file_path:
                        log_entry.status = "error"
                        log_entry.error_message = "No file uploaded. Please upload a zip file containing the chat export."
                        log_entry.completed_at = datetime.now(timezone.utc)
                        db.commit()
                        logger.error(f"No file path set on plugin {plugin_name}")
                        return
                    logger.info(f"Using uploaded file path: {plugin.uploaded_file_path}")
                
                try:
                    log_entry.progress_message = "Checking for new data..."
                    db.commit()
                    
                    # Get the latest imported timestamp for this plugin to only fetch new items (user-specific)
                    latest_item = db.query(DataItem).filter_by(
                        user_id=user_id,
                        plugin_name=plugin_name
                    ).order_by(DataItem.source_timestamp.desc()).first()
                    
                    # Pass the latest timestamp to plugin if it supports incremental imports
                    if latest_item and latest_item.source_timestamp:
                        if hasattr(plugin, 'set_latest_timestamp'):
                            plugin.set_latest_timestamp(latest_item.source_timestamp)
                        log_entry.progress_message = f"Fetching new data since {latest_item.source_timestamp.isoformat()}..."
                    else:
                        log_entry.progress_message = "Fetching data from source (first import)..."
                    db.commit()
                    
                    logger.info(f"Calling fetch_data() for plugin {plugin_name}")
                    data_items = plugin.fetch_data()
                    logger.info(f"Plugin {plugin_name} returned {len(data_items)} items")
                    
                    total_items = len(data_items)
                    log_entry.progress_total = total_items
                    log_entry.progress_current = 0
                    log_entry.progress_message = f"Processing {total_items} items..."
                    db.commit()
                    
                    records_imported = 0
                    items_to_upload = []
                    
                    for idx, item_data in enumerate(data_items):
                        if idx % 10 == 0 or idx == len(data_items) - 1:
                            log_entry.progress_current = idx + 1
                            log_entry.progress_message = f"Processing item {idx + 1} of {total_items}..."
                            db.commit()
                        
                        source_id = item_data.get("source_id")
                        existing = db.query(DataItem).filter_by(
                            user_id=user_id,
                            plugin_name=plugin_name,
                            source_id=source_id
                        ).first()
                        
                        if existing:
                            # For GitHub files, check if content has changed (compare SHA from metadata)
                            should_update = False
                            if plugin_name == "github_context":
                                new_sha = item_data.get("metadata", {}).get("sha")
                                existing_sha = existing.item_metadata.get("sha") if existing.item_metadata else None
                                if new_sha and new_sha != existing_sha:
                                    logger.info(f"GitHub file content changed (SHA: {existing_sha} -> {new_sha}), updating: {source_id}")
                                    should_update = True
                                elif existing.content != item_data.get("content"):
                                    # Fallback: compare content if SHA not available
                                    logger.info(f"GitHub file content changed (content differs), updating: {source_id}")
                                    should_update = True
                            
                            if should_update:
                                # Update existing item
                                existing.title = item_data.get("title")
                                existing.content = item_data.get("content")
                                existing.item_metadata = item_data.get("metadata", {})
                                existing.source_timestamp = item_data.get("source_timestamp")
                                existing.updated_at = datetime.now(timezone.utc)
                                records_imported += 1
                                # Re-upload to vector store since content changed
                                items_to_upload.append(item_data)
                                logger.debug(f"Updated existing item: {source_id} (ID: {existing.id})")
                            else:
                                # Skip existing items that haven't changed
                                logger.debug(f"Skipping unchanged item: {source_id} (already in database, ID: {existing.id})")
                                continue
                        else:
                            new_item = DataItem(
                                user_id=user_id,
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
                            # Collect items for vector store upload
                            items_to_upload.append(item_data)
                    
                    db.commit()
                    
                    skipped_count = total_items - records_imported
                    if skipped_count > 0:
                        logger.info(f"Skipped {skipped_count} existing items for {plugin_name} (user {user_id})")
                    logger.info(f"Saved {records_imported} new items to database for {plugin_name} (user {user_id})")
                    
                    # Upload new items to vector store
                    if items_to_upload:
                        try:
                            from vector_store_service import VectorStoreService
                            vector_store_service = VectorStoreService()
                            
                            logger.info(f"Preparing to upload {len(items_to_upload)} items to vector store for {plugin_name} (user {user_id})")
                            log_entry.progress_message = f"Uploading {len(items_to_upload)} items to vector store..."
                            db.commit()
                            
                            # Upload in batches to avoid overwhelming the API
                            # Increased batch size for better performance
                            batch_size = 500  # Increased from 100 to 500 for faster uploads
                            total_uploaded = 0
                            total_batches = (len(items_to_upload) + batch_size - 1) // batch_size
                            
                            for batch_start in range(0, len(items_to_upload), batch_size):
                                batch_end = min(batch_start + batch_size, len(items_to_upload))
                                batch_items = items_to_upload[batch_start:batch_end]
                                batch_num = batch_start // batch_size + 1
                                
                                log_entry.progress_message = f"Uploading to vector store: batch {batch_num}/{total_batches} ({batch_end}/{len(items_to_upload)} items)..."
                                db.commit()
                                
                                # Only wait for processing on the last batch to ensure data is available
                                # This allows OpenAI to process files in parallel for better performance
                                wait_for_processing = (batch_num == total_batches)
                                logger.info(f"Uploading batch {batch_num}/{total_batches} to vector store for {plugin_name} (user {user_id}): {len(batch_items)} items")
                                success = vector_store_service.upload_data_to_vector_store(plugin_name, batch_items, user_id=user_id, wait_for_processing=wait_for_processing)
                                if success:
                                    total_uploaded += len(batch_items)
                                    logger.info(f"Successfully uploaded batch {batch_num}/{total_batches} to vector store ({batch_end}/{len(items_to_upload)} items) for user {user_id}")
                                else:
                                    logger.warning(f"Failed to upload batch {batch_num}/{total_batches} to vector store for user {user_id}")
                            
                            logger.info(f"Uploaded {total_uploaded} items to vector store for {plugin_name} (user {user_id})")
                            log_entry.progress_message = f"Successfully uploaded {total_uploaded} items to vector store"
                            db.commit()
                        except Exception as e:
                            logger.error(f"Failed to upload to vector store for {plugin_name} (user {user_id}): {e}", exc_info=True)
                            log_entry.progress_message = f"Warning: Vector store upload failed: {str(e)[:200]}"
                            db.commit()
                    else:
                        logger.info(f"No new items to upload to vector store for {plugin_name} (user {user_id}) - {records_imported} items were already in database")
                    
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

