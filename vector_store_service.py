"""Service for managing OpenAI Vector Stores."""
import os
import logging
from typing import Optional, List, Dict, Any
from openai import OpenAI
from pathlib import Path
import tempfile
import json

logger = logging.getLogger(__name__)


class VectorStoreService:
    """Service for managing OpenAI Vector Stores - unified store for all plugins."""
    
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")
        self.client = OpenAI(api_key=api_key)
        self._unified_vector_store_id = None  # Cache unified vector store ID
    
    def get_or_create_unified_vector_store(self) -> Optional[str]:
        """Get or create a unified vector store for all plugins."""
        if self._unified_vector_store_id:
            return self._unified_vector_store_id
        
        # Try to find existing unified vector store (by name)
        # Vector stores are accessed via client.vector_stores (not client.beta.vector_stores)
        try:
            vector_stores = self.client.vector_stores.list(limit=100)
            for vs in vector_stores.data:
                if vs.name == "vector_infinity_unified":
                    logger.info(f"Found existing unified vector store: {vs.id}")
                    self._unified_vector_store_id = vs.id
                    return vs.id
        except Exception as e:
            logger.warning(f"Error listing vector stores: {e}")
        
        # Create new unified vector store
        try:
            vector_store = self.client.vector_stores.create(
                name="vector_infinity_unified",
                description="Unified vector store for all Vector Infinity plugin data"
            )
            logger.info(f"Created new unified vector store: {vector_store.id}")
            self._unified_vector_store_id = vector_store.id
            return vector_store.id
        except Exception as e:
            logger.error(f"Error creating unified vector store: {e}")
            return None
    
    def upload_data_to_vector_store(self, plugin_name: str, data_items: List[Dict[str, Any]], wait_for_processing: bool = False) -> bool:
        """
        Upload data items to the unified vector store.
        
        Args:
            plugin_name: Name of the plugin (for logging/formatting)
            data_items: List of data items with 'title', 'content', 'metadata', etc.
        
        Returns:
            True if successful, False otherwise
        """
        if not data_items:
            logger.info(f"No data items to upload for {plugin_name}")
            return True
        
        vector_store_id = self.get_or_create_unified_vector_store()
        if not vector_store_id:
            logger.error(f"Failed to get/create unified vector store")
            return False
        
        try:
            # Format data items as text for upload
            # Each item becomes a document in the vector store
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
                # Upload file to OpenAI
                with open(temp_file_path, 'rb') as file:
                    uploaded_file = self.client.files.create(
                        file=file,
                        purpose='assistants'
                    )
                
                logger.info(f"Uploaded file {uploaded_file.id} for {plugin_name} to unified vector store")
                
                # Add file to vector store (using client.vector_stores, not client.beta.vector_stores)
                vector_store_file = self.client.vector_stores.files.create(
                    vector_store_id=vector_store_id,
                    file_id=uploaded_file.id
                )
                
                logger.info(f"Added file {uploaded_file.id} to unified vector store {vector_store_id}")
                
                # Optionally wait for vector store to process the file
                # For large imports, it's faster to upload all files first and let OpenAI process in parallel
                if wait_for_processing:
                    import time
                    max_wait = 60  # Reduced to 1 minute for faster batching
                    wait_time = 0
                    while wait_time < max_wait:
                        file_status = self.client.vector_stores.files.retrieve(
                            vector_store_id=vector_store_id,
                            file_id=uploaded_file.id
                        )
                        if file_status.status == 'completed':
                            logger.info(f"Unified vector store file processing completed for {plugin_name}")
                            return True
                        elif file_status.status == 'failed':
                            logger.error(f"Unified vector store file processing failed for {plugin_name}")
                            return False
                        time.sleep(2)
                        wait_time += 2
                    
                    logger.warning(f"Unified vector store file processing timeout for {plugin_name} (still uploaded)")
                
                # File is uploaded and will be processed by OpenAI in the background
                return True
                
            finally:
                # Clean up temp file
                try:
                    os.unlink(temp_file_path)
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"Error uploading data to unified vector store for {plugin_name}: {e}", exc_info=True)
            return False
    
    def get_unified_vector_store_id(self) -> Optional[str]:
        """Get the unified vector store ID."""
        return self._unified_vector_store_id or self.get_or_create_unified_vector_store()
    
    def get_vector_store_info(self) -> Optional[Dict[str, Any]]:
        """Get information about the unified vector store including file count and size."""
        vector_store_id = self.get_unified_vector_store_id()
        if not vector_store_id:
            return None
        
        try:
            # Get vector store details
            vector_store = self.client.vector_stores.retrieve(vector_store_id)
            
            # List files in the vector store
            files = self.client.vector_stores.files.list(vector_store_id=vector_store_id, limit=100)
            file_count = len(files.data) if hasattr(files, 'data') else 0
            
            # Calculate total size of files in vector store
            total_size_bytes = 0
            file_ids = []
            if hasattr(files, 'data'):
                for file_item in files.data:
                    file_ids.append(file_item.id)
            
            # Get file sizes from OpenAI Files API
            for file_id in file_ids:
                try:
                    file_info = self.client.files.retrieve(file_id)
                    if hasattr(file_info, 'bytes') and file_info.bytes:
                        total_size_bytes += file_info.bytes
                except Exception as e:
                    logger.warning(f"Could not get size for file {file_id}: {e}")
            
            # Convert to human-readable format
            size = float(total_size_bytes)
            size_human = "0 B"
            for unit in ['B', 'KB', 'MB', 'GB']:
                if size < 1024.0:
                    size_human = f"{size:.2f} {unit}"
                    break
                size /= 1024.0
            else:
                size_human = f"{size:.2f} TB"
            
            return {
                "id": vector_store.id,
                "name": vector_store.name,
                "file_count": file_count,
                "status": getattr(vector_store, 'status', 'unknown'),
                "total_size_bytes": total_size_bytes,
                "total_size": size_human
            }
        except Exception as e:
            logger.error(f"Error getting vector store info: {e}", exc_info=True)
            return None

