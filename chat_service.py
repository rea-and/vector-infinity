"""Service for managing Gemini 3 conversations with context retrieval from vector store."""
import os
import logging
from typing import Optional, List, Dict, Any
import google.generativeai as genai
from database import UserSettings, ChatThread, DataItem, SessionLocal
import config
import re

logger = logging.getLogger(__name__)

DEFAULT_INSTRUCTIONS = "You are a helpful assistant that can answer questions using both your general knowledge and any relevant context from imported data (Gmail, WhatsApp, WHOOP, etc.). Answer questions naturally and directly. If you find relevant information in the imported data, mention the source when helpful. If the question is about general topics not covered in the imported data, answer using your general knowledge without mentioning that the information wasn't found in the files. Be concise and helpful."


class ChatService:
    """Service for managing Gemini 3 conversations with context retrieval."""
    
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required")
        genai.configure(api_key=api_key)
        self.genai = genai
    
    def _get_instructions(self, user_id: int = None) -> str:
        """Get chat instructions for a user (custom or default)."""
        if user_id is None:
            return DEFAULT_INSTRUCTIONS
        
        db = SessionLocal()
        try:
            settings = db.query(UserSettings).filter(UserSettings.user_id == user_id).first()
            if settings and settings.assistant_instructions:
                return settings.assistant_instructions
            return DEFAULT_INSTRUCTIONS
        finally:
            db.close()
    
    def _get_model(self, user_id: int = None) -> str:
        """Get chat model for a user (custom or default)."""
        if user_id is None:
            return "gemini-3-pro-preview"
        
        db = SessionLocal()
        try:
            settings = db.query(UserSettings).filter(UserSettings.user_id == user_id).first()
            if settings and settings.assistant_model:
                # Check if it's a Gemini model
                if settings.assistant_model.startswith("gemini-"):
                logger.debug(f"Using user-selected model: {settings.assistant_model} for user {user_id}")
                return settings.assistant_model
            return "gemini-3-pro-preview"
        finally:
            db.close()
    
    def _get_thinking_level(self, user_id: int = None) -> str:
        """Get thinking level for Gemini 3 (low or high)."""
        # Default to high for better reasoning, can be made configurable later
        return "high"
    
    def _retrieve_relevant_context(
        self, 
        query: str, 
        user_id: int, 
        max_items: int = 20,
        max_tokens: int = 500000  # Leave room for conversation and response
    ) -> str:
        """
        Retrieve relevant context from the database based on the query.
        Uses keyword matching to find relevant items.
        
        Args:
            query: User's query
            user_id: User ID
            max_items: Maximum number of items to retrieve
            max_tokens: Maximum tokens to use for context (rough estimate: 1 token ≈ 4 chars)
        
        Returns:
            Formatted context string
        """
        db = SessionLocal()
        try:
            # Extract keywords from query (simple approach)
            query_lower = query.lower()
            keywords = [word for word in re.findall(r'\b\w+\b', query_lower) if len(word) > 2]
            
            # Get all data items for this user
            all_items = db.query(DataItem).filter(
                DataItem.user_id == user_id
            ).order_by(DataItem.source_timestamp.desc() if DataItem.source_timestamp else DataItem.created_at.desc()).all()
            
            if not all_items:
                return ""
            
            # Score items based on keyword matches
            scored_items = []
            for item in all_items:
                score = 0
                search_text = f"{item.title or ''} {item.content or ''}".lower()
                
                # Exact phrase match (highest priority)
                if query_lower in search_text:
                    score += 100
                
                # Keyword matches
                for keyword in keywords:
                    if keyword in search_text:
                        score += 10
                
                # Boost recent items
                if item.source_timestamp:
                    from datetime import datetime, timezone, timedelta
                    days_ago = (datetime.now(timezone.utc) - item.source_timestamp).days
                    if days_ago < 7:
                        score += 5
                    elif days_ago < 30:
                        score += 2
                
                if score > 0:
                    scored_items.append((score, item))
            
            # Sort by score and take top items
            scored_items.sort(key=lambda x: x[0], reverse=True)
            selected_items = scored_items[:max_items]
            
            # Format context
            context_parts = []
            total_chars = 0
            max_chars = max_tokens * 4  # Rough estimate
            
            for score, item in selected_items:
                # Format the item similar to how it's stored in vector store
                item_parts = []
                item_parts.append(f"Source: {item.plugin_name}")
                
                if item.item_type == "whatsapp_message":
                    item_parts.append("Type: WhatsApp Message")
                    if item.item_metadata and item.item_metadata.get("sender"):
                        item_parts.append(f"From: {item.item_metadata['sender']}")
                    if item.source_timestamp:
                        item_parts.append(f"Date: {item.source_timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
                    if item.content:
                        item_parts.append(item.content)
                elif item.item_type in ["whoop_recovery", "whoop_sleep", "whoop_workout"]:
                    item_parts.append(f"Type: WHOOP {item.item_type.replace('whoop_', '').title()}")
                    if item.title:
                        item_parts.append(item.title)
                    if item.source_timestamp:
                        item_parts.append(f"Date: {item.source_timestamp.strftime('%Y-%m-%d')}")
                    if item.content:
                        item_parts.append(item.content)
                elif item.item_type == "github_file":
                    item_parts.append("Type: GitHub File")
                    if item.title:
                        item_parts.append(f"File: {item.title}")
                    if item.item_metadata:
                        if item.item_metadata.get("github_url"):
                            item_parts.append(f"URL: {item.item_metadata['github_url']}")
                        if item.item_metadata.get("repo"):
                            item_parts.append(f"Repository: {item.item_metadata['repo']}")
                        if item.item_metadata.get("path"):
                            item_parts.append(f"Path: {item.item_metadata['path']}")
                    if item.source_timestamp:
                        item_parts.append(f"Date: {item.source_timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
                    if item.content:
                        item_parts.append(item.content)
                else:  # email and other types
                    item_parts.append("Type: Email")
                    if item.title:
                        item_parts.append(f"Subject: {item.title}")
                    if item.item_metadata and item.item_metadata.get("from"):
                        item_parts.append(f"From: {item.item_metadata['from']}")
                    if item.source_timestamp:
                        item_parts.append(f"Date: {item.source_timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
                    if item.content:
                        item_parts.append(item.content)
                
                formatted_item = "\n".join(item_parts)
                item_chars = len(formatted_item)
                
                if total_chars + item_chars > max_chars:
                    break
                
                context_parts.append(formatted_item)
                total_chars += item_chars
            
            if context_parts:
                return "\n\n---\n\n".join(context_parts)
            return ""
                    
            except Exception as e:
            logger.error(f"Error retrieving context: {e}", exc_info=True)
            return ""
        finally:
            db.close()
    
    def send_message(
        self, 
        message: str, 
        thread_id: Optional[str] = None,
        vector_store_id: Optional[str] = None,  # Not used, kept for compatibility
        user_id: int = None,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        Send a message using Gemini 3 with context retrieval.
        
        Args:
            message: User message
            thread_id: Thread ID (for conversation continuity, stored in database)
            vector_store_id: Not used (kept for backward compatibility)
            user_id: User ID for user-specific settings
            conversation_history: Previous conversation messages (optional)
        
        Returns:
            Dictionary with:
            - response_id: Thread ID (for tracking)
            - content: AI response text
            - openai_thread_id: Thread ID (stored in openai_thread_id field for database compatibility)
            - messages: Updated conversation history
        """
        if not user_id:
            raise ValueError("user_id is required")
        
        model = self._get_model(user_id)
        instructions = self._get_instructions(user_id)
        thinking_level = self._get_thinking_level(user_id)
        
        # Get conversation history from database if thread exists and not provided
        if conversation_history is None:
            conversation_history = []
            if thread_id:
                db = SessionLocal()
                try:
                    chat_thread = db.query(ChatThread).filter(
                        ChatThread.openai_thread_id == thread_id,  # Reusing field name for compatibility
                        ChatThread.user_id == user_id
                    ).first()
                    if chat_thread and chat_thread.conversation_history:
                        conversation_history = chat_thread.conversation_history
                finally:
                    db.close()
        
        # Retrieve relevant context from database
        context = self._retrieve_relevant_context(message, user_id)
        
        # Build the prompt with context
        system_prompt = instructions
        if context:
            system_prompt += f"\n\nHere is relevant context from your imported data:\n\n{context}\n\nUse this context to answer the user's question. If the context doesn't contain relevant information, use your general knowledge."
        
        # Prepare messages for Gemini
        # Build the full prompt with context and conversation history
        full_prompt_parts = []
        
        # Add system instructions and context at the beginning
        if system_prompt:
            full_prompt_parts.append(system_prompt)
        
        # Add conversation history
        for msg in conversation_history:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                full_prompt_parts.append(f"User: {content}")
            elif role == "assistant":
                full_prompt_parts.append(f"Assistant: {content}")
        
        # Add current user message
        full_prompt_parts.append(f"User: {message}")
        full_prompt_parts.append("Assistant:")
        
        full_prompt = "\n\n".join(full_prompt_parts)
        
        # Generate response
        try:
            # Use google-generativeai SDK
            generation_config = {
                "temperature": 1.0,  # Gemini 3 default
            }
            
            # Create the model
            model_instance = self.genai.GenerativeModel(
                model_name=model,
                generation_config=generation_config
            )
            
            # Generate content
            # Note: thinking_level parameter may need to be passed differently
            # For now, we'll use the standard API and add thinking_level support when available
            response = model_instance.generate_content(full_prompt)
            
            # Extract response text (google-generativeai format)
            response_text = response.text if hasattr(response, 'text') else str(response)
            
            # Update conversation history
            updated_history = conversation_history + [
                {"role": "user", "content": message},
                {"role": "assistant", "content": response_text}
            ]
            
            logger.info(f"Successfully sent message using Gemini 3 (model: {model}, thread: {thread_id})")
        
        return {
                "response_id": thread_id or "gemini_thread",
            "content": response_text,
                "openai_thread_id": thread_id,  # Store in openai_thread_id field for database compatibility
                "messages": updated_history
        }
            
        except Exception as e:
            logger.error(f"Error generating response with Gemini 3: {e}", exc_info=True)
            raise Exception(f"Failed to generate response: {str(e)}")
