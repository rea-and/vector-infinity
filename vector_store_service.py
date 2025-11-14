"""OpenAI Vector Store service for managing vector stores."""
import os
import json
import logging
from typing import Optional, List, Dict
from pathlib import Path
from openai import OpenAI
import config

logger = logging.getLogger(__name__)


class VectorStoreService:
    """Service for managing OpenAI Vector Stores."""
    
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required for Vector Store API")
        self.client = OpenAI(api_key=api_key)
        self.stores_dir = config.BASE_DIR / "data" / "vector_stores"
        self.stores_dir.mkdir(parents=True, exist_ok=True)
    
    def get_or_create_store(self, plugin_name: str) -> str:
        """Get existing vector store ID or create a new one for a plugin."""
        store_info_path = self.stores_dir / f"{plugin_name}_store.json"
        
        # Check if store already exists
        if store_info_path.exists():
            try:
                with open(store_info_path, 'r') as f:
                    store_info = json.load(f)
                    store_id = store_info.get("store_id")
                    if store_id:
                        # Verify store still exists
                        try:
                            store = self.client.beta.vector_stores.retrieve(store_id)
                            logger.info(f"Using existing vector store {store_id} for {plugin_name}")
                            return store_id
                        except Exception as e:
                            logger.warning(f"Vector store {store_id} not found, creating new one: {e}")
            except Exception as e:
                logger.warning(f"Error reading store info: {e}")
        
        # Create new vector store
        logger.info(f"Creating new vector store for {plugin_name}")
        try:
            # Try the beta.vector_stores API
            vector_store = self.client.beta.vector_stores.create(
                name=f"{plugin_name}_vector_store",
                description=f"Vector store for {plugin_name} plugin data"
            )
        except AttributeError:
            # Fallback: try accessing through assistants API
            try:
                # Vector stores might be accessed differently in some SDK versions
                vector_store = self.client.beta.assistants.vector_stores.create(
                    name=f"{plugin_name}_vector_store",
                    description=f"Vector store for {plugin_name} plugin data"
                )
            except AttributeError:
                # Last resort: try direct access
                logger.error("Vector stores API not available in this OpenAI SDK version. Please upgrade: pip install --upgrade openai>=1.12.0")
                raise ValueError("Vector stores API not available. Please upgrade OpenAI SDK: pip install --upgrade openai>=1.12.0")
        
        # Save store info
        store_info = {
            "store_id": vector_store.id,
            "plugin_name": plugin_name,
            "created_at": vector_store.created_at
        }
        with open(store_info_path, 'w') as f:
            json.dump(store_info, f, indent=2)
        
        logger.info(f"Created vector store {vector_store.id} for {plugin_name}")
        return vector_store.id
    
    def sync_data_to_store(self, plugin_name: str, data_items: List[Dict]) -> Dict:
        """
        Sync data items to a vector store.
        
        Args:
            plugin_name: Name of the plugin
            data_items: List of data items with 'title', 'content', 'metadata', etc.
        
        Returns:
            Dict with sync status and file batch ID
        """
        if not data_items:
            return {"status": "skipped", "reason": "No data items to sync"}
        
        store_id = self.get_or_create_store(plugin_name)
        
        # Prepare data for upload
        # Format each item as a text document
        documents = []
        for item in data_items:
            # Create a formatted text document
            doc_lines = []
            if item.get("title"):
                doc_lines.append(f"Subject: {item['title']}")
            if item.get("metadata", {}).get("from"):
                doc_lines.append(f"From: {item['metadata']['from']}")
            if item.get("source_timestamp"):
                doc_lines.append(f"Date: {item['source_timestamp']}")
            doc_lines.append("")  # Blank line
            if item.get("content"):
                doc_lines.append(item["content"])
            
            doc_text = "\n".join(doc_lines)
            documents.append(doc_text)
        
        # Create a temporary file with all documents
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write("\n\n---EMAIL_SEPARATOR---\n\n".join(documents))
            temp_file_path = f.name
        
        try:
            # Upload file to OpenAI
            with open(temp_file_path, 'rb') as f:
                file = self.client.files.create(
                    file=f,
                    purpose="assistants"
                )
            
            # Create file batch and attach to vector store
            file_batch = self.client.beta.assistants.vector_stores.file_batches.create(
                vector_store_id=store_id,
                file_ids=[file.id]
            )
            
            logger.info(f"Created file batch {file_batch.id} for {plugin_name} with {len(data_items)} items")
            
            return {
                "status": "success",
                "store_id": store_id,
                "file_batch_id": file_batch.id,
                "file_id": file.id,
                "items_count": len(data_items)
            }
        finally:
            # Clean up temp file
            try:
                os.unlink(temp_file_path)
            except:
                pass
    
    def get_store_id(self, plugin_name: str) -> Optional[str]:
        """Get the vector store ID for a plugin if it exists."""
        store_info_path = self.stores_dir / f"{plugin_name}_store.json"
        if store_info_path.exists():
            try:
                with open(store_info_path, 'r') as f:
                    store_info = json.load(f)
                    return store_info.get("store_id")
            except:
                return None
        return None
    
    def delete_store(self, plugin_name: str) -> bool:
        """Delete a vector store for a plugin."""
        store_id = self.get_store_id(plugin_name)
        if not store_id:
            return False
        
        try:
            self.client.beta.assistants.vector_stores.delete(store_id)
            store_info_path = self.stores_dir / f"{plugin_name}_store.json"
            if store_info_path.exists():
                store_info_path.unlink()
            logger.info(f"Deleted vector store {store_id} for {plugin_name}")
            return True
        except Exception as e:
            logger.error(f"Error deleting vector store: {e}")
            return False

