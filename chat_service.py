"""Service for managing Gemini 3 conversations with context retrieval."""
import os
import logging
from typing import Optional, List, Dict, Any
from gemini_chat_service import GeminiChatService
from database import UserSettings, ChatThread, SessionLocal
import config

logger = logging.getLogger(__name__)


class ChatService:
    """Service for managing Gemini 3 conversations with context retrieval."""
    
    def __init__(self):
        # Initialize Gemini service
        self.gemini_service = GeminiChatService()
    
    def send_message(
        self, 
        message: str, 
        thread_id: Optional[str] = None,
        vector_store_id: Optional[str] = None,  # Not used, kept for compatibility
        user_id: int = None
    ) -> Dict[str, Any]:
        """
        Send a message using Gemini 3 with context retrieval.
        
        Args:
            message: User message
            thread_id: Thread ID (for conversation continuity)
            vector_store_id: Not used (kept for backward compatibility)
            user_id: User ID for user-specific settings
        
        Returns:
            Dictionary with:
            - response_id: Thread ID (for tracking)
            - content: AI response text
            - thread_id: Thread ID
            - messages: Updated conversation history
        """
        if not user_id:
            raise ValueError("user_id is required")
        
        # Get conversation history from database if thread exists
        conversation_history = None
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
        
        result = self.gemini_service.send_message(
            message=message,
            thread_id=thread_id,
            user_id=user_id,
            conversation_history=conversation_history
        )
        
        # Return in expected format
        return {
            "response_id": result.get("response_id", result.get("thread_id", "gemini_thread")),
            "content": result["content"],
            "openai_thread_id": result.get("thread_id"),  # Store in openai_thread_id field for database compatibility
            "messages": result["messages"]
        }
