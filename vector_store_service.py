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
    """Service for managing OpenAI Vector Stores per plugin."""
    
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")
        self.client = OpenAI(api_key=api_key)
        self._vector_store_cache = {}  # Cache vector store IDs per plugin
    
    def get_or_create_vector_store(self, plugin_name: str) -> Optional[str]:
        """Get or create a vector store for a plugin."""
        if plugin_name in self._vector_store_cache:
            return self._vector_store_cache[plugin_name]
        
        # Try to find existing vector store (by name)
        try:
            vector_stores = self.client.beta.vector_stores.list(limit=100)
            for vs in vector_stores.data:
                if vs.name == f"vector_infinity_{plugin_name}":
                    logger.info(f"Found existing vector store for {plugin_name}: {vs.id}")
                    self._vector_store_cache[plugin_name] = vs.id
                    return vs.id
        except Exception as e:
            logger.warning(f"Error listing vector stores: {e}")
        
        # Create new vector store
        try:
            vector_store = self.client.beta.vector_stores.create(
                name=f"vector_infinity_{plugin_name}",
                description=f"Vector store for {plugin_name} plugin data"
            )
            logger.info(f"Created new vector store for {plugin_name}: {vector_store.id}")
            self._vector_store_cache[plugin_name] = vector_store.id
            return vector_store.id
        except Exception as e:
            logger.error(f"Error creating vector store for {plugin_name}: {e}")
            return None
    
    def upload_data_to_vector_store(self, plugin_name: str, data_items: List[Dict[str, Any]]) -> bool:
        """
        Upload data items to a vector store.
        
        Args:
            plugin_name: Name of the plugin
            data_items: List of data items with 'title', 'content', 'metadata', etc.
        
        Returns:
            True if successful, False otherwise
        """
        if not data_items:
            logger.info(f"No data items to upload for {plugin_name}")
            return True
        
        vector_store_id = self.get_or_create_vector_store(plugin_name)
        if not vector_store_id:
            logger.error(f"Failed to get/create vector store for {plugin_name}")
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
                
                # Format the document
                doc_parts = []
                
                if item_type == "whatsapp_message":
                    if metadata.get("sender"):
                        doc_parts.append(f"From: {metadata['sender']}")
                    if source_timestamp:
                        doc_parts.append(f"Date: {source_timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
                    if content:
                        doc_parts.append(content)
                elif item_type in ["whoop_recovery", "whoop_sleep", "whoop_workout"]:
                    if title:
                        doc_parts.append(title)
                    if source_timestamp:
                        doc_parts.append(f"Date: {source_timestamp.strftime('%Y-%m-%d')}")
                    if content:
                        doc_parts.append(content)
                else:  # email and other types
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
                
                logger.info(f"Uploaded file {uploaded_file.id} for {plugin_name}")
                
                # Add file to vector store
                vector_store_file = self.client.beta.vector_stores.files.create(
                    vector_store_id=vector_store_id,
                    file_id=uploaded_file.id
                )
                
                logger.info(f"Added file {uploaded_file.id} to vector store {vector_store_id}")
                
                # Wait for vector store to process the file
                import time
                max_wait = 300  # 5 minutes max
                wait_time = 0
                while wait_time < max_wait:
                    file_status = self.client.beta.vector_stores.files.retrieve(
                        vector_store_id=vector_store_id,
                        file_id=uploaded_file.id
                    )
                    if file_status.status == 'completed':
                        logger.info(f"Vector store file processing completed for {plugin_name}")
                        return True
                    elif file_status.status == 'failed':
                        logger.error(f"Vector store file processing failed for {plugin_name}")
                        return False
                    time.sleep(2)
                    wait_time += 2
                
                logger.warning(f"Vector store file processing timeout for {plugin_name}")
                return True  # Still return True as file was uploaded
                
            finally:
                # Clean up temp file
                try:
                    os.unlink(temp_file_path)
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"Error uploading data to vector store for {plugin_name}: {e}", exc_info=True)
            return False
    
    def get_vector_store_id(self, plugin_name: str) -> Optional[str]:
        """Get the vector store ID for a plugin."""
        return self._vector_store_cache.get(plugin_name) or self.get_or_create_vector_store(plugin_name)

