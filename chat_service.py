"""Service for managing OpenAI Assistants API conversations with vector store support."""
import os
import logging
from typing import Optional, List, Dict, Any
from openai import OpenAI
from database import UserSettings, ChatThread, SessionLocal
import config
import time

logger = logging.getLogger(__name__)

DEFAULT_INSTRUCTIONS = "You are a helpful assistant that can answer questions using both your general knowledge and any relevant context from imported data (Gmail, WhatsApp, WHOOP, etc.). Answer questions naturally and directly. If you find relevant information in the imported data, mention the source when helpful. If the question is about general topics not covered in the imported data, answer using your general knowledge without mentioning that the information wasn't found in the files. Be concise and helpful."


class ChatService:
    """Service for managing OpenAI Assistants API conversations with vector store support."""
    
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
                logger.debug(f"Using user-selected model: {settings.assistant_model} for user {user_id}")
                return settings.assistant_model
            return config.DEFAULT_MODEL
        finally:
            db.close()
    
    def get_or_create_assistant(self, user_id: int, vector_store_id: Optional[str] = None) -> str:
        """Get or create a persistent assistant for a user."""
        db = SessionLocal()
        try:
            settings = db.query(UserSettings).filter(UserSettings.user_id == user_id).first()
            if not settings:
                # Create UserSettings if it doesn't exist
                settings = UserSettings(user_id=user_id)
                db.add(settings)
                db.commit()
                db.refresh(settings)
            
            # Check if we have an existing assistant ID
            if settings.assistant_id:
                try:
                    # Verify the assistant still exists
                    assistant = self.client.beta.assistants.retrieve(settings.assistant_id)
                    logger.info(f"Using existing assistant {settings.assistant_id} for user {user_id}")
                    
                    # Update vector store if it changed
                    if vector_store_id and assistant.tool_resources and assistant.tool_resources.file_search:
                        current_vs_ids = assistant.tool_resources.file_search.vector_store_ids or []
                        if vector_store_id not in current_vs_ids:
                            logger.info(f"Updating assistant {settings.assistant_id} with new vector store {vector_store_id}")
                            self.client.beta.assistants.update(
                                settings.assistant_id,
                                tool_resources={
                                    "file_search": {
                                        "vector_store_ids": [vector_store_id]
                                    }
                                }
                            )
                    
                    return settings.assistant_id
                except Exception as e:
                    logger.warning(f"Assistant {settings.assistant_id} not found, creating new one: {e}")
                    settings.assistant_id = None
            
            # Create new assistant
            instructions = self._get_instructions(user_id)
            model = self._get_model(user_id)
            
            assistant_params = {
                "name": f"Vector Infinity Assistant (User {user_id})",
                "instructions": instructions,
                "model": model,
                "tools": [{"type": "file_search"}] if vector_store_id else []
            }
            
            if vector_store_id:
                assistant_params["tool_resources"] = {
                    "file_search": {
                        "vector_store_ids": [vector_store_id]
                    }
                }
            
            assistant = self.client.beta.assistants.create(**assistant_params)
            
            # Save assistant ID to database
            settings.assistant_id = assistant.id
            from datetime import datetime, timezone
            settings.updated_at = datetime.now(timezone.utc)
            db.commit()
            
            logger.info(f"Created new assistant {assistant.id} for user {user_id}")
            return assistant.id
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error getting/creating assistant for user {user_id}: {e}", exc_info=True)
            raise
        finally:
            db.close()
    
    def update_assistant_if_needed(self, user_id: int, vector_store_id: Optional[str] = None):
        """Update assistant if model or instructions changed."""
        db = SessionLocal()
        try:
            settings = db.query(UserSettings).filter(UserSettings.user_id == user_id).first()
            if not settings or not settings.assistant_id:
                return
            
            try:
                assistant = self.client.beta.assistants.retrieve(settings.assistant_id)
                needs_update = False
                update_params = {}
                
                # Check if model changed
                current_model = self._get_model(user_id)
                if assistant.model != current_model:
                    update_params["model"] = current_model
                    needs_update = True
                
                # Check if instructions changed
                current_instructions = self._get_instructions(user_id)
                if assistant.instructions != current_instructions:
                    update_params["instructions"] = current_instructions
                    needs_update = True
                
                # Check if vector store changed
                if vector_store_id:
                    current_vs_ids = []
                    if assistant.tool_resources and assistant.tool_resources.file_search:
                        current_vs_ids = assistant.tool_resources.file_search.vector_store_ids or []
                    
                    if vector_store_id not in current_vs_ids:
                        update_params["tool_resources"] = {
                            "file_search": {
                                "vector_store_ids": [vector_store_id]
                            }
                        }
                        needs_update = True
                
                if needs_update:
                    logger.info(f"Updating assistant {settings.assistant_id} for user {user_id}")
                    self.client.beta.assistants.update(settings.assistant_id, **update_params)
                    
            except Exception as e:
                logger.warning(f"Error updating assistant: {e}")
        finally:
            db.close()
    
    def send_message(
        self, 
        message: str, 
        openai_thread_id: Optional[str] = None,
        vector_store_id: Optional[str] = None,
        user_id: int = None
    ) -> Dict[str, Any]:
        """
        Send a message using Assistants API with vector store support.
        
        Args:
            message: User message
            openai_thread_id: OpenAI Thread ID (if continuing existing conversation)
            vector_store_id: Vector store ID for file search
            user_id: User ID for user-specific settings
        
        Returns:
            Dictionary with:
            - response_id: Run ID (for tracking)
            - content: AI response text
            - openai_thread_id: OpenAI Thread ID
            - messages: Updated conversation history (for backward compatibility)
        """
        if not user_id:
            raise ValueError("user_id is required")
        
        # Get or create assistant for user
        assistant_id = self.get_or_create_assistant(user_id, vector_store_id)
        
        # Update assistant if settings changed
        self.update_assistant_if_needed(user_id, vector_store_id)
        
        # Get or create OpenAI thread
        if openai_thread_id:
            try:
                # Verify thread exists
                thread = self.client.beta.threads.retrieve(openai_thread_id)
            except Exception as e:
                logger.warning(f"Thread {openai_thread_id} not found, creating new one: {e}")
                openai_thread_id = None
        
        if not openai_thread_id:
            thread = self.client.beta.threads.create()
            openai_thread_id = thread.id
            logger.info(f"Created new OpenAI thread {openai_thread_id}")
        
        # Add user message to thread
        self.client.beta.threads.messages.create(
            thread_id=openai_thread_id,
            role="user",
            content=message
        )
        
        # Run the assistant
        run = self.client.beta.threads.runs.create(
            thread_id=openai_thread_id,
            assistant_id=assistant_id
        )
        
        # Wait for completion
        max_wait = 120  # Increased timeout for vector store searches
        wait_time = 0
        while wait_time < max_wait:
            run_status = self.client.beta.threads.runs.retrieve(
                thread_id=openai_thread_id,
                run_id=run.id
            )
            
            if run_status.status == "completed":
                break
            elif run_status.status == "failed":
                error_msg = "Unknown error"
                if hasattr(run_status, 'last_error') and run_status.last_error:
                    error_msg = str(run_status.last_error)
                raise Exception(f"Assistant run failed: {error_msg}")
            elif run_status.status in ["cancelled", "expired"]:
                raise Exception(f"Assistant run {run_status.status}")
            
            time.sleep(1)
            wait_time += 1
        
        if wait_time >= max_wait:
            raise Exception("Assistant run timeout")
        
        # Get the response
        messages = self.client.beta.threads.messages.list(
            thread_id=openai_thread_id,
            order="asc"
        )
        
        # Extract the assistant's response (last message from assistant)
        response_text = ""
        for msg in reversed(messages.data):
            if msg.role == "assistant":
                if msg.content and len(msg.content) > 0:
                    if hasattr(msg.content[0], 'text'):
                        response_text = msg.content[0].text.value
                    elif isinstance(msg.content[0], dict) and 'text' in msg.content[0]:
                        response_text = msg.content[0]['text'].get('value', '')
                    break
        
        if not response_text:
            raise Exception("No response from assistant")
        
        # Build conversation history for backward compatibility
        conversation_history = []
        for msg in messages.data:
            if msg.role in ["user", "assistant"]:
                content = ""
                if msg.content and len(msg.content) > 0:
                    if hasattr(msg.content[0], 'text'):
                        content = msg.content[0].text.value
                    elif isinstance(msg.content[0], dict) and 'text' in msg.content[0]:
                        content = msg.content[0]['text'].get('value', '')
                conversation_history.append({
                    "role": msg.role,
                    "content": content
                })
        
        logger.info(f"Successfully sent message using Assistants API (assistant: {assistant_id}, thread: {openai_thread_id})")
        
        return {
            "response_id": run.id,
            "content": response_text,
            "openai_thread_id": openai_thread_id,
            "messages": conversation_history  # For backward compatibility
        }
