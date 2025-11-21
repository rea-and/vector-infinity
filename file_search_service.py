"""Service for managing File Search Stores (RAG) for context retrieval."""
import os
import logging
from typing import Optional, List, Dict, Any
from google import genai
from google.genai import types
import tempfile
import json
import time

logger = logging.getLogger(__name__)


class FileSearchService:
    """Service for managing File Search Stores - unified store for all plugins."""
    
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required")
        self.client = genai.Client(api_key=api_key)
        self._unified_store_id = None  # Cache unified store ID
    
    def get_or_create_unified_file_search_store(self, user_id: int = None) -> Optional[str]:
        """Get or create a unified file search store for all plugins (user-specific)."""
        # Use user-specific cache key
        cache_key = f"user_{user_id}" if user_id else "default"
        if hasattr(self, f'_unified_store_id_{cache_key}'):
            return getattr(self, f'_unified_store_id_{cache_key}')
        
        store_name = f"vector_infinity_unified_user_{user_id}" if user_id else "vector_infinity_unified"
        
        # Try to find existing unified file search store
        try:
            stores = self.client.file_search_stores.list()
            for store in stores:
                if hasattr(store, 'display_name') and store.display_name == store_name:
                    logger.info(f"Found existing unified file search store for user {user_id}: {store.name}")
                    setattr(self, f'_unified_store_id_{cache_key}', store.name)
                    return store.name
        except Exception as e:
            logger.warning(f"Error listing file search stores: {e}")
        
        # Create new unified file search store
        try:
            # Use dict format as shown in documentation
            store = self.client.file_search_stores.create(
                config={'display_name': store_name}
            )
            logger.info(f"Created new unified file search store for user {user_id}: {store.name}")
            setattr(self, f'_unified_store_id_{cache_key}', store.name)
            return store.name
        except Exception as e:
            logger.error(f"Error creating unified file search store: {e}")
            return None
    
    def upload_data_to_file_search_store(
        self, 
        plugin_name: str, 
        data_items: List[Dict[str, Any]], 
        user_id: int = None, 
        wait_for_processing: bool = False
    ) -> bool:
        """
        Upload data items to the unified file search store (user-specific).
        
        Args:
            plugin_name: Name of the plugin (for logging/formatting)
            data_items: List of data items with 'title', 'content', 'metadata', etc.
            user_id: User ID for user-specific stores
            wait_for_processing: Whether to wait for file processing to complete
        
        Returns:
            True if successful, False otherwise
        """
        if not data_items:
            logger.info(f"No data items to upload for {plugin_name}")
            return True
        
        store_name = self.get_or_create_unified_file_search_store(user_id=user_id)
        if not store_name:
            logger.error(f"Failed to get/create unified file search store")
            return False
        
        try:
            # Format data items as text for upload
            # Each item becomes a document in the file search store
            formatted_items = []
            for item in data_items:
                item_type = item.get("item_type", "")
                title = item.get("title", "")
                content = item.get("content", "")
                metadata = item.get("metadata", {})
                source_timestamp = item.get("source_timestamp")
                
                # Format the document with plugin context
                doc_parts = []
                doc_parts.append(f"Source: {plugin_name}")
                
                if item_type == "whatsapp_message":
                    doc_parts.append("Type: WhatsApp Message")
                    if metadata.get("sender"):
                        doc_parts.append(f"From: {metadata['sender']}")
                    if source_timestamp:
                        doc_parts.append(f"Date: {source_timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
                    if content:
                        doc_parts.append(content)
                elif item_type in ["whoop_recovery", "whoop_sleep", "whoop_workout"]:
                    doc_parts.append(f"Type: WHOOP {item_type.replace('whoop_', '').title()}")
                    if title:
                        doc_parts.append(title)
                    if source_timestamp:
                        doc_parts.append(f"Date: {source_timestamp.strftime('%Y-%m-%d')}")
                    if content:
                        doc_parts.append(content)
                elif item_type == "github_file":
                    doc_parts.append("Type: GitHub File")
                    if title:
                        doc_parts.append(f"File: {title}")
                    if metadata.get("github_url"):
                        doc_parts.append(f"URL: {metadata['github_url']}")
                    if metadata.get("repo"):
                        doc_parts.append(f"Repository: {metadata['repo']}")
                    if metadata.get("path"):
                        doc_parts.append(f"Path: {metadata['path']}")
                    if source_timestamp:
                        doc_parts.append(f"Date: {source_timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
                    if content:
                        doc_parts.append(content)
                else:  # email and other types
                    doc_parts.append("Type: Email")
                    if title:
                        doc_parts.append(f"Subject: {title}")
                    if metadata.get("from"):
                        doc_parts.append(f"From: {metadata['from']}")
                    if source_timestamp:
                        doc_parts.append(f"Date: {source_timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
                    if content:
                        doc_parts.append(content)
                
                formatted_items.append("\n".join(doc_parts))
            
            # Create a temporary file with all items
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
                f.write("\n\n---\n\n".join(formatted_items))
                temp_file_path = f.name
            
            try:
                # Upload file to Files API
                with open(temp_file_path, 'rb') as file:
                    uploaded_file = self.client.files.upload(
                        file=file,
                        config={'display_name': f"{plugin_name}_batch_{int(time.time())}"}
                    )
                
                logger.info(f"Uploaded file {uploaded_file.name} for {plugin_name} to Files API")
                
                # Import file into file search store
                import_op = self.client.file_search_stores.import_file(
                    file_search_store_name=store_name,
                    file_name=uploaded_file.name
                )
                
                logger.info(f"Imported file {uploaded_file.name} into file search store {store_name}")
                
                # Optionally wait for processing
                if wait_for_processing:
                    max_wait = 120  # 2 minutes
                    wait_time = 0
                    while wait_time < max_wait:
                        # Check operation status
                        try:
                            op = self.client.operations.get(name=import_op.name)
                            if op.done:
                                if hasattr(op, 'error') and op.error:
                                    logger.error(f"File search store import failed: {op.error}")
                                    return False
                                logger.info(f"File search store import completed for {plugin_name}")
                                return True
                        except Exception as e:
                            logger.warning(f"Error checking operation status: {e}")
                        
                        time.sleep(2)
                        wait_time += 2
                    
                    logger.warning(f"File search store import timeout for {plugin_name} (still processing)")
                
                # File is imported and will be processed in the background
                return True
                
            finally:
                # Clean up temp file
                try:
                    os.unlink(temp_file_path)
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"Error uploading data to file search store for {plugin_name}: {e}", exc_info=True)
            return False
    
    def get_unified_file_search_store_name(self, user_id: int = None) -> Optional[str]:
        """Get the unified file search store name (cached, user-specific)."""
        cache_key = f"user_{user_id}" if user_id else "default"
        cached_name = getattr(self, f'_unified_store_id_{cache_key}', None)
        return cached_name or self.get_or_create_unified_file_search_store(user_id=user_id)
    
    def get_file_search_store_info(self, user_id: int = None) -> Optional[Dict[str, Any]]:
        """Get information about the unified file search store."""
        store_name = self.get_unified_file_search_store_name(user_id=user_id)
        if not store_name:
            return None
        
        try:
            # Get store details
            store = self.client.file_search_stores.get(name=store_name)
            
            # List files in the store
            # Note: The API structure might be different - try multiple approaches
            file_count = 0
            try:
                # Try the correct API structure for listing files in a File Search Store
                # Files are managed through the Files API and associated with stores
                # We'll try to get file count through the store's file associations
                try:
                    # Method 1: Try direct files listing if available
                    if hasattr(self.client, 'file_search_stores') and hasattr(self.client.file_search_stores, 'files'):
                        files_response = self.client.file_search_stores.files.list(parent=store_name, page_size=100)
                        if hasattr(files_response, 'file_search_store_files'):
                            file_count = len(list(files_response.file_search_store_files))
                except AttributeError:
                    # Method 2: Try listing all files and checking which are in this store
                    # This is a workaround - we can't directly list files in a store
                    # So we'll return None for file_count and let the user check via re-upload
                    logger.info("Cannot directly list files in File Search Store - file count unavailable")
                    file_count = None
                except Exception as e:
                    logger.warning(f"Could not list files in store: {e}")
                    file_count = None
                
                if file_count is not None:
                    logger.info(f"File Search Store {store_name} has {file_count} files")
            except Exception as e:
                logger.warning(f"Could not list files in store: {e}")
                file_count = None
            
            result = {
                "name": store.name,
                "display_name": getattr(store, 'display_name', 'Unknown'),
                "status": "active"
            }
            
            if file_count is not None:
                result["file_count"] = file_count
            else:
                result["file_count"] = "unknown"
                result["note"] = "File count unavailable - check if files were uploaded during import"
            
            return result
        except Exception as e:
            logger.error(f"Error getting file search store info: {e}", exc_info=True)
            return None
    
    def list_files_in_store(self, user_id: int = None) -> List[Dict[str, Any]]:
        """List all files in the File Search Store."""
        store_name = self.get_unified_file_search_store_name(user_id=user_id)
        if not store_name:
            return []
        
        try:
            files = []
            # Note: The API for listing files in a File Search Store may not be directly available
            # Files are managed through the Files API and associated with stores via import_file
            # We cannot directly query which files are in a specific store
            logger.warning("Direct file listing for File Search Store is not available in the API")
            return files
        except Exception as e:
            logger.error(f"Error listing files in store: {e}", exc_info=True)
            return []

