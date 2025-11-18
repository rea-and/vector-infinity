"""Service for managing OpenAI Chat Completions API conversations."""
import os
import logging
from typing import Optional, List, Dict, Any
from openai import OpenAI
from database import UserSettings, SessionLocal
import config

logger = logging.getLogger(__name__)

DEFAULT_INSTRUCTIONS = "You are a helpful assistant that can answer questions using both your general knowledge and any relevant context from imported data (Gmail, WhatsApp, WHOOP, etc.). Answer questions naturally and directly. If you find relevant information in the imported data, mention the source when helpful. If the question is about general topics not covered in the imported data, answer using your general knowledge without mentioning that the information wasn't found in the files. Be concise and helpful."


class ChatService:
    """Service for managing OpenAI Chat Completions API conversations."""
    
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")
        self.client = OpenAI(api_key=api_key)
    
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
            return config.DEFAULT_MODEL
        
        db = SessionLocal()
        try:
            settings = db.query(UserSettings).filter(UserSettings.user_id == user_id).first()
            if settings and settings.assistant_model:
                # Validate that the user's model is still in the available models list
                if settings.assistant_model in config.AVAILABLE_MODELS:
                    return settings.assistant_model
                # If user's model is no longer available, fall back to default
                logger.warning(f"User {user_id} has model {settings.assistant_model} which is no longer available, using default")
            return config.DEFAULT_MODEL
        finally:
            db.close()
    
    def send_message(
        self, 
        message: str, 
        conversation_history: Optional[List[Dict[str, str]]] = None,
        vector_store_id: Optional[str] = None,
        user_id: int = None
    ) -> Dict[str, Any]:
        """
        Send a message using chat.completions API.
        Manages conversation history locally.
        
        Args:
            message: User message
            conversation_history: Previous conversation messages (list of {"role": "user/assistant", "content": "..."})
            vector_store_id: Vector store ID for file search
            user_id: User ID for user-specific settings
        
        Returns:
            Dictionary with:
            - response_id: Response ID (for tracking)
            - content: AI response text
            - messages: Updated conversation history including new exchange
        """
        try:
            instructions = self._get_instructions(user_id)
            model = self._get_model(user_id)
            
            # Build messages list with system instruction and conversation history
            messages_list = [
                {"role": "system", "content": instructions}
            ]
            
            # Add conversation history if provided
            if conversation_history:
                messages_list.extend(conversation_history)
            
            # Add current user message
            messages_list.append({"role": "user", "content": message})
            
            # Build request parameters
            request_params = {
                "model": model,
                "messages": messages_list
            }
            
            # Add vector store for file search if provided
            if vector_store_id:
                request_params["tools"] = [{"type": "file_search"}]
                request_params["tool_resources"] = {
                    "file_search": {
                        "vector_store_ids": [vector_store_id]
                    }
                }
            
            # Call chat.completions API
            response = self.client.chat.completions.create(**request_params)
            
            # Extract response content
            response_text = response.choices[0].message.content
            response_id = response.id
            
            # Build updated conversation history
            updated_history = conversation_history.copy() if conversation_history else []
            updated_history.append({"role": "user", "content": message})
            updated_history.append({"role": "assistant", "content": response_text})
            
            return {
                "response_id": response_id,
                "content": response_text,
                "messages": updated_history
            }
            
        except Exception as e:
            logger.error(f"Error sending message: {e}", exc_info=True)
            # Check if it's an unsupported model error
            error_str = str(e)
            if "unsupported_model" in error_str or "cannot be used" in error_str:
                logger.error(f"Model {model} is not supported. Falling back to default model {config.DEFAULT_MODEL}")
                # Clear the invalid model from user settings
                if user_id:
                    self._clear_invalid_model(user_id, model)
                # Retry with default model - rebuild request_params to ensure consistency
                fallback_model = config.DEFAULT_MODEL
                fallback_params = {
                    "model": fallback_model,
                    "messages": messages_list  # Reuse the same messages list
                }
                if vector_store_id:
                    fallback_params["tools"] = [{"type": "file_search"}]
                    fallback_params["tool_resources"] = {
                        "file_search": {
                            "vector_store_ids": [vector_store_id]
                        }
                    }
                try:
                    response = self.client.chat.completions.create(**fallback_params)
                    response_text = response.choices[0].message.content
                    response_id = response.id
                    
                    updated_history = conversation_history.copy() if conversation_history else []
                    updated_history.append({"role": "user", "content": message})
                    updated_history.append({"role": "assistant", "content": response_text})
                    
                    return {
                        "response_id": response_id,
                        "content": response_text,
                        "messages": updated_history
                    }
                except Exception as retry_error:
                    logger.error(f"Error with default model: {retry_error}", exc_info=True)
                    return None
            return None
    
    def _clear_invalid_model(self, user_id: int, invalid_model: str):
        """Clear an invalid model from user settings and fall back to default."""
        db = SessionLocal()
        try:
            settings = db.query(UserSettings).filter(UserSettings.user_id == user_id).first()
            if settings and settings.assistant_model == invalid_model:
                settings.assistant_model = None
                from datetime import datetime, timezone
                settings.updated_at = datetime.now(timezone.utc)
                db.commit()
                logger.info(f"Cleared invalid model '{invalid_model}' for user {user_id}, reset to default")
        except Exception as e:
            logger.warning(f"Error clearing invalid model for user {user_id}: {e}")
            db.rollback()
        finally:
            db.close()

