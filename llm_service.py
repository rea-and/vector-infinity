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
                "response": "Error: OpenAI API key not configured. Please set OPENAI_API_KEY in your .env file.",
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
            
            # If context is empty and vector search was used, try fallback
            if not context and use_vector_search:
                logger.info("Vector search returned no results (possibly due to quota), falling back to date-based search")
                context = self.build_context(
                    query_text=prompt,
                    limit=context_limit,
                    plugin_names=plugin_names,
                    use_vector_search=False
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
            
            # GPT-5 uses max_completion_tokens instead of max_tokens
            # Try max_completion_tokens first, fallback to max_tokens for older models
            try:
                response = client.chat.completions.create(
                    model=config.OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": full_prompt}
                    ],
                    temperature=0.7,
                    max_completion_tokens=2000
                )
            except Exception as e:
                # Fallback for older models that use max_tokens
                if "max_completion_tokens" in str(e) or "unsupported_parameter" in str(e):
                    response = client.chat.completions.create(
                        model=config.OPENAI_MODEL,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": full_prompt}
                        ],
                        temperature=0.7,
                        max_tokens=2000
                    )
                else:
                    raise
            
            return {
                "response": response.choices[0].message.content,
                "context_used": context[:1000] + "..." if len(context) > 1000 else context,
                "error": None
            }
        
        except Exception as e:
            error_msg = str(e)
            error_type = "unknown"
            user_message = "Error generating response"
            
            # Check for specific error types
            if "429" in error_msg or "quota" in error_msg.lower() or "insufficient_quota" in error_msg.lower():
                error_type = "quota_exceeded"
                user_message = "OpenAI API quota exceeded. Please check your billing and usage at https://platform.openai.com/usage. You may need to add credits to your account or upgrade your plan."
                # Log quota errors without full traceback (expected user error, not system error)
                logger.warning(f"OpenAI API quota exceeded: {error_msg}")
            elif "rate_limit" in error_msg.lower():
                error_type = "rate_limit"
                user_message = "OpenAI API rate limit exceeded. Please try again in a few moments."
                logger.warning(f"OpenAI API rate limit exceeded: {error_msg}")
            elif "invalid_api_key" in error_msg.lower() or "authentication" in error_msg.lower():
                error_type = "auth_error"
                user_message = "OpenAI API key is invalid. Please check your API key in the .env file."
                logger.error(f"OpenAI API authentication error: {error_msg}")
            elif "unsupported_parameter" in error_msg.lower() or "400" in error_msg:
                error_type = "api_error"
                user_message = f"API request error: {error_msg}. This may be due to an incompatible model parameter."
                logger.error(f"OpenAI API parameter error: {error_msg}")
            else:
                user_message = f"Error generating response: {error_msg}"
                # Log unexpected errors with full traceback for debugging
                logger.error(f"Error generating LLM response ({error_type}): {e}", exc_info=True)
            
            return {
                "response": user_message,
                "context_used": "",
                "error": error_type,
                "error_details": error_msg
            }

