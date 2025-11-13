"""Vector database management using ChromaDB."""
import chromadb
from chromadb.config import Settings
from typing import List, Dict, Any, Optional
import config
import logging
from openai import OpenAI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VectorDB:
    """Manages vector database operations using ChromaDB."""
    
    def __init__(self):
        """Initialize ChromaDB client and collection."""
        # Use persistent client for low RAM (in-memory would use more)
        self.client = chromadb.PersistentClient(
            path=str(config.VECTOR_DB_PATH),
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )
        
        # Get or create collection
        self.collection = self.client.get_or_create_collection(
            name="data_items",
            metadata={"hnsw:space": "cosine"}  # Use cosine similarity
        )
        
        # Initialize OpenAI client for embeddings
        self.openai_client = None
        if config.OPENAI_API_KEY:
            self.openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
        else:
            logger.warning("OpenAI API key not set - embeddings will not work")
    
    def generate_embedding(self, text: str) -> Optional[List[float]]:
        """Generate embedding for text using OpenAI."""
        if not self.openai_client:
            return None
        
        try:
            # Truncate text if too long (OpenAI has limits)
            max_chars = 8000  # Safe limit for text-embedding-3-small
            if len(text) > max_chars:
                text = text[:max_chars]
            
            response = self.openai_client.embeddings.create(
                model=config.EMBEDDING_MODEL,
                input=text
            )
            return response.data[0].embedding
        except Exception as e:
            error_msg = str(e)
            # Check for quota/rate limit errors
            if "429" in error_msg or "quota" in error_msg.lower() or "rate_limit" in error_msg.lower():
                logger.error(f"OpenAI API quota/rate limit exceeded. Please check your billing and usage: {e}")
            else:
                logger.error(f"Error generating embedding: {e}")
            return None
    
    def add_item(self, item_id: str, text: str, metadata: Dict[str, Any]) -> bool:
        """
        Add an item to the vector database.
        
        Args:
            item_id: Unique identifier (should match DataItem.id)
            text: Text content to embed
            metadata: Additional metadata to store
        
        Returns:
            True if successful, False otherwise
        """
        embedding = self.generate_embedding(text)
        if not embedding:
            return False
        
        try:
            # Convert metadata values to strings (ChromaDB requirement)
            chroma_metadata = {}
            for key, value in metadata.items():
                if value is not None:
                    chroma_metadata[key] = str(value)
            
            self.collection.add(
                ids=[str(item_id)],
                embeddings=[embedding],
                documents=[text],
                metadatas=[chroma_metadata]
            )
            return True
        except Exception as e:
            logger.error(f"Error adding item to vector DB: {e}")
            return False
    
    def update_item(self, item_id: str, text: str, metadata: Dict[str, Any]) -> bool:
        """Update an existing item in the vector database."""
        # ChromaDB update is essentially delete + add
        try:
            self.delete_item(item_id)
            return self.add_item(item_id, text, metadata)
        except Exception as e:
            logger.error(f"Error updating item in vector DB: {e}")
            return False
    
    def delete_item(self, item_id: str) -> bool:
        """Delete an item from the vector database."""
        try:
            self.collection.delete(ids=[str(item_id)])
            return True
        except Exception as e:
            logger.error(f"Error deleting item from vector DB: {e}")
            return False
    
    def search(self, query_text: str, limit: int = 10, 
               filter_metadata: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Search for similar items using semantic search.
        
        Args:
            query_text: Query text to search for
            limit: Maximum number of results
            filter_metadata: Optional metadata filters (e.g., {"plugin_name": "gmail_personal"})
        
        Returns:
            List of results with id, distance, document, and metadata
        """
        query_embedding = self.generate_embedding(query_text)
        if not query_embedding:
            return []
        
        try:
            # Convert filter metadata values to strings
            where = None
            if filter_metadata:
                where = {}
                for key, value in filter_metadata.items():
                    where[key] = str(value)
            
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=limit,
                where=where
            )
            
            # Format results
            formatted_results = []
            if results['ids'] and len(results['ids'][0]) > 0:
                for i in range(len(results['ids'][0])):
                    formatted_results.append({
                        'id': results['ids'][0][i],
                        'distance': results['distances'][0][i] if results.get('distances') else None,
                        'document': results['documents'][0][i] if results.get('documents') else None,
                        'metadata': results['metadatas'][0][i] if results.get('metadatas') else {}
                    })
            
            return formatted_results
        except Exception as e:
            logger.error(f"Error searching vector DB: {e}")
            return []
    
    def get_count(self) -> int:
        """Get total number of items in the collection."""
        try:
            return self.collection.count()
        except:
            return 0


# Global instance
_vector_db_instance = None

def get_vector_db() -> VectorDB:
    """Get or create global vector DB instance."""
    global _vector_db_instance
    if _vector_db_instance is None:
        _vector_db_instance = VectorDB()
    return _vector_db_instance

