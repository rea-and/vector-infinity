"""Service for generating and managing embeddings."""
import os
import json
import logging
import numpy as np
from typing import List, Optional
from openai import OpenAI
import config

logger = logging.getLogger(__name__)

# Embedding model to use
EMBEDDING_MODEL = "text-embedding-3-small"  # Small, efficient, good quality


class EmbeddingService:
    """Service for generating embeddings using OpenAI's API."""
    
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required for embeddings")
        self.client = OpenAI(api_key=api_key)
    
    def generate_embedding(self, text: str) -> Optional[List[float]]:
        """Generate an embedding for a single text."""
        if not text or not text.strip():
            return None
        
        try:
            response = self.client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=text
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            return None
    
    def generate_embeddings_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Generate embeddings for multiple texts (batched for efficiency)."""
        if not texts:
            return []
        
        # Filter out empty texts
        valid_texts = [(i, text) for i, text in enumerate(texts) if text and text.strip()]
        if not valid_texts:
            return [None] * len(texts)
        
        indices, valid_texts_list = zip(*valid_texts)
        
        try:
            response = self.client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=list(valid_texts_list)
            )
            
            # Create result list with None for empty texts
            results = [None] * len(texts)
            for idx, embedding_data in zip(indices, response.data):
                results[idx] = embedding_data.embedding
            
            return results
        except Exception as e:
            logger.error(f"Error generating embeddings batch: {e}")
            return [None] * len(texts)
    
    def cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        vec1 = np.array(vec1)
        vec2 = np.array(vec2)
        return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))
    
    def embedding_to_bytes(self, embedding: List[float]) -> bytes:
        """Convert embedding list to bytes for database storage."""
        return json.dumps(embedding).encode('utf-8')
    
    def bytes_to_embedding(self, data: bytes) -> List[float]:
        """Convert bytes from database to embedding list."""
        return json.loads(data.decode('utf-8'))

