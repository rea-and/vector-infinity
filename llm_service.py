"""LLM service for generating prompts with context."""
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from database import DataItem, SessionLocal
from vector_db import get_vector_db
from datetime import datetime, timedelta
import openai
import config
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LLMService:
    """Service for interacting with OpenAI GPT-5."""
    
    def __init__(self):
        if not config.OPENAI_API_KEY:
            logger.warning("OpenAI API key not set")
        else:
            openai.api_key = config.OPENAI_API_KEY
        self.vector_db = get_vector_db()
    
    def build_context(self, query_text: str, limit: int = 10, 
                     plugin_names: List[str] = None, 
                     use_vector_search: bool = True) -> str:
        """
        Build context string using semantic search from vector database.
        
        Args:
            query_text: Query text to search for (used for semantic search)
            limit: Maximum number of items to include
            plugin_names: Optional list of plugin names to filter by
            use_vector_search: If True, use semantic search; if False, use date-based fallback
        
        Returns:
            Formatted context string
        """
        db = SessionLocal()
        try:
            if use_vector_search:
                # Use semantic search from vector database
                filter_metadata = None
                if plugin_names:
                    # Note: ChromaDB where clause can only filter on one value at a time
                    # For multiple plugins, we'll search without filter and filter results
                    pass
                
                # Perform semantic search
                vector_results = self.vector_db.search(
                    query_text=query_text,
                    limit=limit * 2,  # Get more results to filter
                    filter_metadata=filter_metadata
                )
                
                # Get full item details from SQLite
                item_ids = [int(result['id']) for result in vector_results]
                if not item_ids:
                    return ""
                
                items = db.query(DataItem).filter(DataItem.id.in_(item_ids)).all()
                
                # Filter by plugin_names if specified
                if plugin_names:
                    items = [item for item in items if item.plugin_name in plugin_names]
                
                # Sort by relevance (maintain order from vector search)
                item_dict = {item.id: item for item in items}
                sorted_items = []
                for result in vector_results:
                    item_id = int(result['id'])
                    if item_id in item_dict:
                        sorted_items.append(item_dict[item_id])
                        if len(sorted_items) >= limit:
                            break
                
                items = sorted_items
            else:
                # Fallback to date-based search
                cutoff_date = datetime.utcnow() - timedelta(days=30)
                query = db.query(DataItem).filter(
                    DataItem.created_at >= cutoff_date
                )
                
                if plugin_names:
                    query = query.filter(DataItem.plugin_name.in_(plugin_names))
                
                items = query.order_by(DataItem.created_at.desc()).limit(limit).all()
            
            # Format context
            context_parts = []
            for item in items:
                item_str = f"[{item.plugin_name}] {item.item_type}"
                if item.title:
                    item_str += f": {item.title}"
                if item.content:
                    item_str += f"\n{item.content[:1000]}"  # Increased limit since we're being selective
                if item.source_timestamp:
                    item_str += f"\nDate: {item.source_timestamp.isoformat()}"
                context_parts.append(item_str)
            
            return "\n\n---\n\n".join(context_parts)
        
        finally:
            db.close()
    
    def generate_response(self, prompt: str, context_limit: int = 10, 
                         plugin_names: List[str] = None,
                         use_vector_search: bool = True) -> Dict[str, Any]:
        """
        Generate a response using GPT-5 with context from imported data.
        Uses semantic search to find the most relevant items.
        
        Args:
            prompt: User's prompt/question (also used for semantic search)
            context_limit: Maximum number of data items to include as context
            plugin_names: Optional list of plugin names to filter context
            use_vector_search: If True, use semantic search; if False, use date-based fallback
        
        Returns:
            Dictionary with 'response' and 'context_used' keys
        """
        if not config.OPENAI_API_KEY:
            return {
                "response": "Error: OpenAI API key not configured",
                "context_used": "",
                "error": "API key missing"
            }
        
        try:
            # Build context using semantic search
            context = self.build_context(
                query_text=prompt,
                limit=context_limit,
                plugin_names=plugin_names,
                use_vector_search=use_vector_search
            )
            
            # Build full prompt with context
            system_prompt = """You are a helpful assistant with access to the user's personal data including emails, 
            todos, health data, calendar events, and more. Use the provided context to answer questions accurately 
            and helpfully. If the context doesn't contain relevant information, say so."""
            
            full_prompt = f"""Context from user's data:

{context}

---

User question: {prompt}

Please provide a helpful response based on the context above."""
            
            # Call OpenAI API
            client = openai.OpenAI(api_key=config.OPENAI_API_KEY)
            response = client.chat.completions.create(
                model=config.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": full_prompt}
                ],
                temperature=0.7,
                max_tokens=2000
            )
            
            return {
                "response": response.choices[0].message.content,
                "context_used": context[:1000] + "..." if len(context) > 1000 else context,
                "error": None
            }
        
        except Exception as e:
            logger.error(f"Error generating LLM response: {e}", exc_info=True)
            return {
                "response": f"Error generating response: {str(e)}",
                "context_used": "",
                "error": str(e)
            }

