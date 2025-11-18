"""Service for managing OpenAI Chat Completions API conversations with vector store support."""
import os
import logging
from typing import Optional, List, Dict, Any
from openai import OpenAI
from database import UserSettings, SessionLocal
import config

logger = logging.getLogger(__name__)

DEFAULT_INSTRUCTIONS = "You are a helpful assistant that can answer questions using both your general knowledge and any relevant context from imported data (Gmail, WhatsApp, WHOOP, etc.). Answer questions naturally and directly. If you find relevant information in the imported data, mention the source when helpful. If the question is about general topics not covered in the imported data, answer using your general knowledge without mentioning that the information wasn't found in the files. Be concise and helpful."


class ChatService:
    """Service for managing OpenAI Chat Completions API conversations with vector store support."""
    
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
                # Return the user's selected model even if not in AVAILABLE_MODELS
                # (AVAILABLE_MODELS is just for the UI dropdown - user may have selected
                # a model that was later removed from the list, or a model not in the default list)
                # We'll validate it works when actually calling the API
                logger.debug(f"Using user-selected model: {settings.assistant_model} for user {user_id}")
                return settings.assistant_model
            return config.DEFAULT_MODEL
        finally:
            db.close()
    
    def send_message(
        self, 
        message: str, 
        conversation_history: Optional[List[Dict[str, str]]] = None,
        vector_store_id: Optional[str] = None,
        user_id: int = None,
        previous_response_id: Optional[str] = None  # Kept for backward compatibility, but not used
    ) -> Dict[str, Any]:
        """
        Send a message using Chat Completions API with vector store support.
        
        Args:
            message: User message
            conversation_history: Previous conversation messages
            vector_store_id: Vector store ID for file search
            user_id: User ID for user-specific settings
            previous_response_id: Not used (kept for backward compatibility)
        
        Returns:
            Dictionary with:
            - response_id: Response ID (for tracking)
            - content: AI response text
            - messages: Updated conversation history
        """
        instructions = self._get_instructions(user_id)
        model = self._get_model(user_id)
        
        return self._send_message_chat_completions_api(
            message=message,
            instructions=instructions,
            model=model,
            conversation_history=conversation_history,
            vector_store_id=vector_store_id,
            user_id=user_id
        )
    
    def _send_message_chat_completions_api(
        self,
        message: str,
        instructions: str,
        model: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        vector_store_id: Optional[str] = None,
        user_id: int = None
    ) -> Dict[str, Any]:
        """Send a message using Chat Completions API with vector store support."""
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
        # Chat Completions API uses both 'tools' and 'tool_resources' parameters for vector stores
        if vector_store_id:
            request_params["tools"] = [{"type": "file_search"}]
            request_params["tool_resources"] = {
                "file_search": {
                    "vector_store_ids": [vector_store_id]
                }
            }
            logger.info(f"Using vector store {vector_store_id} for file search via tools and tool_resources (Chat Completions API)")
            
        try:
            # Call chat.completions API
            response = self.client.chat.completions.create(**request_params)
            
            # Extract response content
            response_text = response.choices[0].message.content
            response_id = response.id
            
            # Build updated conversation history
            updated_history = conversation_history.copy() if conversation_history else []
            updated_history.append({"role": "user", "content": message})
            updated_history.append({"role": "assistant", "content": response_text})
            
            logger.info(f"Successfully sent message using Chat Completions API (model: {model})")
            
            return {
                "response_id": response_id,
                "content": response_text,
                "messages": updated_history
            }
            
        except Exception as e:
            logger.error(f"Error sending message with Chat Completions API: {e}", exc_info=True)
            error_str = str(e)
            
            # Check if it's an unsupported model error
            if ("unsupported_model" in error_str or 
                "cannot be used" in error_str or 
                "not in v1/chat/completions" in error_str):
                
                logger.error(f"Model {model} is not supported by Chat Completions API. Falling back to default model...")
                # Try with default model
                if model != config.DEFAULT_MODEL:
                    try:
                        return self._send_message_chat_completions_api(
                            message=message,
                            instructions=instructions,
                            model=config.DEFAULT_MODEL,
                            conversation_history=conversation_history,
                            vector_store_id=vector_store_id,
                            user_id=user_id
                        )
                    except Exception as fallback_error:
                        logger.error(f"Default model also failed: {fallback_error}")
                        # Clear invalid model from user settings
                        if user_id:
                            self._clear_invalid_model(user_id, model)
                        raise Exception(f"Model {model} is not supported. Please select a different model.")
                else:
                    raise Exception(f"Default model {config.DEFAULT_MODEL} is not supported. Please check your configuration.")
            
            # Check if tool_resources is not supported (try with tools parameter as fallback)
            if "tool_resources" in error_str.lower() and ("unexpected keyword argument" in error_str.lower() or "not supported" in error_str.lower()):
                logger.warning(f"Chat Completions API doesn't support tool_resources for model {model}. Trying tools parameter...")
                # Try with tools parameter instead
                try:
                    request_params_tools = {
                        "model": model,
                        "messages": messages_list,
                        "tools": [{
                            "type": "file_search",
                            "vector_store_ids": [vector_store_id]
                        }]
                    }
                    logger.info(f"Trying Chat Completions API with tools parameter for vector store {vector_store_id}")
                    response = self.client.chat.completions.create(**request_params_tools)
                    
                    response_text = response.choices[0].message.content
                    response_id = response.id
                    
                    updated_history = conversation_history.copy() if conversation_history else []
                    updated_history.append({"role": "user", "content": message})
                    updated_history.append({"role": "assistant", "content": response_text})
                    
                    logger.info(f"Successfully used Chat Completions API with tools parameter (model: {model})")
                    return {
                        "response_id": response_id,
                        "content": response_text,
                        "messages": updated_history
                    }
                except Exception as tools_error:
                    logger.warning(f"Chat Completions with tools parameter also failed: {tools_error}")
                    # If both fail, try without vector store
                    logger.warning(f"Vector store search not supported for model {model}. Retrying without vector store...")
                    request_params_no_vector = {
                        "model": model,
                        "messages": messages_list
                    }
                    response = self.client.chat.completions.create(**request_params_no_vector)
                    
                    response_text = response.choices[0].message.content
                    response_id = response.id
                    
                    updated_history = conversation_history.copy() if conversation_history else []
                    updated_history.append({"role": "user", "content": message})
                    updated_history.append({"role": "assistant", "content": response_text})
                    
                    logger.warning(f"Sent message without vector store (model {model} doesn't support file_search)")
                    return {
                        "response_id": response_id,
                        "content": response_text,
                        "messages": updated_history
                    }
            
            # For other errors, re-raise
            raise
    
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
