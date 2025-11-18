"""Service for managing OpenAI Assistants and chat."""
import os
import logging
from typing import Optional, List, Dict, Any
from openai import OpenAI
from database import UserSettings, SessionLocal
import config

logger = logging.getLogger(__name__)

DEFAULT_INSTRUCTIONS = "You are a helpful assistant that can answer questions using both your general knowledge and any relevant context from imported data (Gmail, WhatsApp, WHOOP, etc.). Answer questions naturally and directly. If you find relevant information in the imported data, mention the source when helpful. If the question is about general topics not covered in the imported data, answer using your general knowledge without mentioning that the information wasn't found in the files. Be concise and helpful."


class AssistantService:
    """Service for managing OpenAI Assistants and chat threads."""
    
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")
        self.client = OpenAI(api_key=api_key)
        self._unified_assistant_id = None  # Cache unified assistant ID
    
    def _get_instructions(self, user_id: int = None) -> str:
        """Get assistant instructions for a user (custom or default)."""
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
        """Get assistant model for a user (custom or default)."""
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
    
    def get_or_create_unified_assistant(self, vector_store_id: str, user_id: int = None) -> Optional[str]:
        """
        Get or create a unified assistant for all plugins (user-specific).
        
        Args:
            vector_store_id: Unified vector store ID
            user_id: User ID for user-specific assistant
        
        Returns:
            Assistant ID or None
        """
        instructions = self._get_instructions(user_id)
        model = self._get_model(user_id)
        cache_key = f"user_{user_id}" if user_id else "default"
        cached_id = getattr(self, f'_unified_assistant_id_{cache_key}', None)
        assistant_name = f"vector_infinity_unified_user_{user_id}" if user_id else "vector_infinity_unified"
        
        if cached_id:
            # Verify assistant still exists and update vector store if needed
            try:
                assistant = self.client.beta.assistants.retrieve(cached_id)
                # Update vector store if it changed, or instructions if they changed, or model if it changed
                current_vs_ids = []
                if assistant.tool_resources and assistant.tool_resources.file_search:
                    current_vs_ids = assistant.tool_resources.file_search.vector_store_ids or []
                
                if [vector_store_id] != current_vs_ids or assistant.instructions != instructions or assistant.model != model:
                    # Update assistant with new vector store, instructions, and/or model
                    try:
                        assistant = self.client.beta.assistants.update(
                            assistant.id,
                            instructions=instructions,
                            model=model,
                            tool_resources={
                                "file_search": {
                                    "vector_store_ids": [vector_store_id]
                                }
                            }
                        )
                        logger.info(f"Updated unified assistant {assistant.id} with new vector store, instructions, and/or model")
                    except Exception as update_error:
                        # Check if it's an unsupported model error
                        error_str = str(update_error)
                        if "unsupported_model" in error_str or "cannot be used with the Assistants API" in error_str:
                            logger.error(f"Model {model} is not supported by Assistants API. Falling back to default model {config.DEFAULT_MODEL}")
                            # Clear the invalid model from user settings
                            if user_id:
                                self._clear_invalid_model(user_id, model)
                            # Retry with default model
                            model = config.DEFAULT_MODEL
                            assistant = self.client.beta.assistants.update(
                                assistant.id,
                                instructions=instructions,
                                model=model,
                                tool_resources={
                                    "file_search": {
                                        "vector_store_ids": [vector_store_id]
                                    }
                                }
                            )
                            logger.info(f"Updated unified assistant {assistant.id} with default model {model}")
                        else:
                            raise
                
                return assistant.id
            except Exception as e:
                logger.warning(f"Error retrieving unified assistant: {e}, creating new one")
                # Fall through to create new assistant
        
        # Try to find existing unified assistant by name
        try:
            assistants = self.client.beta.assistants.list(limit=100)
            for assistant in assistants.data:
                if assistant.name == assistant_name:
                    logger.info(f"Found existing unified assistant for user {user_id}: {assistant.id}")
                    # Update vector store, instructions, and model
                    try:
                        assistant = self.client.beta.assistants.update(
                            assistant.id,
                            instructions=instructions,
                            model=model,
                            tool_resources={
                                "file_search": {
                                    "vector_store_ids": [vector_store_id]
                                }
                            }
                        )
                    except Exception as update_error:
                        # Check if it's an unsupported model error
                        error_str = str(update_error)
                        if "unsupported_model" in error_str or "cannot be used with the Assistants API" in error_str:
                            logger.error(f"Model {model} is not supported by Assistants API. Falling back to default model {config.DEFAULT_MODEL}")
                            # Clear the invalid model from user settings
                            if user_id:
                                self._clear_invalid_model(user_id, model)
                            # Retry with default model
                            model = config.DEFAULT_MODEL
                            assistant = self.client.beta.assistants.update(
                                assistant.id,
                                instructions=instructions,
                                model=model,
                                tool_resources={
                                    "file_search": {
                                        "vector_store_ids": [vector_store_id]
                                    }
                                }
                            )
                            logger.info(f"Updated unified assistant {assistant.id} with default model {model}")
                        else:
                            raise
                    setattr(self, f'_unified_assistant_id_{cache_key}', assistant.id)
                    return assistant.id
        except Exception as e:
            logger.warning(f"Error listing assistants: {e}")
        
        # Create new unified assistant
        try:
            tool_resources = {
                "file_search": {
                    "vector_store_ids": [vector_store_id]
                }
            }
            
            try:
                assistant = self.client.beta.assistants.create(
                    name=assistant_name,
                    instructions=instructions,
                    model=model,
                    tools=[{"type": "file_search"}],
                    tool_resources=tool_resources
                )
                logger.info(f"Created new unified assistant for user {user_id}: {assistant.id} with model {model}")
            except Exception as create_error:
                # Check if it's an unsupported model error
                error_str = str(create_error)
                if "unsupported_model" in error_str or "cannot be used with the Assistants API" in error_str:
                    logger.error(f"Model {model} is not supported by Assistants API. Falling back to default model {config.DEFAULT_MODEL}")
                    # Clear the invalid model from user settings
                    if user_id:
                        self._clear_invalid_model(user_id, model)
                    # Retry with default model
                    model = config.DEFAULT_MODEL
                    assistant = self.client.beta.assistants.create(
                        name=assistant_name,
                        instructions=instructions,
                        model=model,
                        tools=[{"type": "file_search"}],
                        tool_resources=tool_resources
                    )
                    logger.info(f"Created new unified assistant for user {user_id}: {assistant.id} with default model {model}")
                else:
                    raise
            
            setattr(self, f'_unified_assistant_id_{cache_key}', assistant.id)
            return assistant.id
        except Exception as e:
            logger.error(f"Error creating unified assistant: {e}")
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
    
    def create_thread(self) -> Optional[str]:
        """Create a new chat thread."""
        try:
            thread = self.client.beta.threads.create()
            return thread.id
        except Exception as e:
            logger.error(f"Error creating thread: {e}")
            return None
    
    def send_message(self, thread_id: str, assistant_id: str, message: str) -> Optional[str]:
        """
        Send a message to a thread and get the response.
        
        Args:
            thread_id: Thread ID
            assistant_id: Assistant ID
            message: User message
        
        Returns:
            Assistant's response text or None
        """
        try:
            # Add user message to thread
            self.client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=message
            )
            
            # Create a run
            run = self.client.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=assistant_id
            )
            
            # Wait for run to complete
            import time
            max_wait = 60  # 1 minute max
            wait_time = 0
            while wait_time < max_wait:
                run = self.client.beta.threads.runs.retrieve(
                    thread_id=thread_id,
                    run_id=run.id
                )
                
                if run.status == 'completed':
                    # Get the assistant's response
                    messages = self.client.beta.threads.messages.list(
                        thread_id=thread_id,
                        order='asc'
                    )
                    # Get the last assistant message
                    for msg in reversed(messages.data):
                        if msg.role == 'assistant':
                            if msg.content[0].type == 'text':
                                return msg.content[0].text.value
                    return None
                elif run.status == 'failed':
                    logger.error(f"Run failed: {run.last_error}")
                    return None
                elif run.status in ['cancelled', 'expired']:
                    logger.error(f"Run {run.status}")
                    return None
                
                time.sleep(1)
                wait_time += 1
            
            logger.error("Run timeout")
            return None
            
        except Exception as e:
            logger.error(f"Error sending message: {e}", exc_info=True)
            return None
    
    def get_thread_messages(self, thread_id: str) -> List[Dict[str, Any]]:
        """Get all messages from a thread."""
        try:
            messages = self.client.beta.threads.messages.list(
                thread_id=thread_id,
                order='asc'
            )
            
            result = []
            for msg in messages.data:
                if msg.content[0].type == 'text':
                    result.append({
                        'role': msg.role,
                        'content': msg.content[0].text.value,
                        'created_at': msg.created_at
                    })
            return result
        except Exception as e:
            logger.error(f"Error getting thread messages: {e}")
            return []

