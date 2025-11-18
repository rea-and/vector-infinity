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
        """Send a message using Chat Completions API with vector store support via Assistants API."""
        # If we have a vector store, use Assistants API to search it, then Chat Completions for response
        if vector_store_id:
            logger.info(f"Using Assistants API to search vector store {vector_store_id}, then Chat Completions for response")
            return self._send_message_with_vector_store_search(
                message=message,
                instructions=instructions,
                model=model,
                conversation_history=conversation_history,
                vector_store_id=vector_store_id,
                user_id=user_id
            )
        
        # No vector store - use Chat Completions directly
        return self._send_message_chat_completions_only(
            message=message,
            instructions=instructions,
            model=model,
            conversation_history=conversation_history,
            user_id=user_id
        )
    
    def _send_message_with_vector_store_search(
        self,
        message: str,
        instructions: str,
        model: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        vector_store_id: Optional[str] = None,
        user_id: int = None
    ) -> Dict[str, Any]:
        """Use Assistants API to search vector store, then Chat Completions for final response."""
        import uuid
        import time
        
        # Step 1: Use Assistants API to search the vector store
        assistant = None
        thread = None
        try:
            # Create a temporary assistant with vector store access
            assistant = self.client.beta.assistants.create(
                name=f"Vector Search {uuid.uuid4().hex[:8]}",
                instructions="You are a search assistant. Search the provided vector store for relevant information to answer the user's question. Return only the relevant information found, without additional commentary.",
                model=model,
                tool_resources={
                    "file_search": {
                        "vector_store_ids": [vector_store_id]
                    }
                } if vector_store_id else None,
                tools=[{"type": "file_search"}] if vector_store_id else []
            )
            
            # Create a thread
            thread = self.client.beta.threads.create()
            
            # Add current message to thread
            self.client.beta.threads.messages.create(
                thread_id=thread.id,
                role="user",
                content=message
            )
            
            # Run the assistant to search the vector store
            run = self.client.beta.threads.runs.create(
                thread_id=thread.id,
                assistant_id=assistant.id
            )
            
            # Wait for completion
            max_wait = 60
            wait_time = 0
            while wait_time < max_wait:
                run_status = self.client.beta.threads.runs.retrieve(
                    thread_id=thread.id,
                    run_id=run.id
                )
                
                if run_status.status == "completed":
                    break
                elif run_status.status == "failed":
                    raise Exception(f"Assistant run failed: {run_status.last_error}")
                elif run_status.status in ["cancelled", "expired"]:
                    raise Exception(f"Assistant run {run_status.status}")
                
                time.sleep(1)
                wait_time += 1
            
            if wait_time >= max_wait:
                raise Exception("Assistant run timeout")
            
            # Get the search results from the assistant
            messages = self.client.beta.threads.messages.list(
                thread_id=thread.id,
                order="asc"
            )
            
            # Extract the assistant's response (search results)
            search_results = ""
            for msg in reversed(messages.data):
                if msg.role == "assistant":
                    if msg.content and len(msg.content) > 0:
                        if hasattr(msg.content[0], 'text'):
                            search_results = msg.content[0].text.value
                        elif isinstance(msg.content[0], dict) and 'text' in msg.content[0]:
                            search_results = msg.content[0]['text'].get('value', '')
                        break
            
            if not search_results:
                logger.warning("No search results from vector store")
                search_results = "No relevant information found in the vector store."
            
            logger.info(f"Retrieved search results from vector store (length: {len(search_results)} chars)")
            
        except Exception as e:
            logger.error(f"Error searching vector store with Assistants API: {e}", exc_info=True)
            # If vector store search fails, continue without it
            search_results = ""
        finally:
            # Clean up assistant and thread
            if thread:
                try:
                    self.client.beta.threads.delete(thread.id)
                except:
                    pass
            if assistant:
                try:
                    self.client.beta.assistants.delete(assistant.id)
                except:
                    pass
        
        # Step 2: Use Chat Completions API with the search results injected into the prompt
        # Build messages list with system instruction and conversation history
        messages_list = [
            {"role": "system", "content": instructions}
        ]
        
        # Add conversation history if provided
        if conversation_history:
            messages_list.extend(conversation_history)
        
        # Add current user message with search results context
        if search_results:
            enhanced_message = f"""Context from your imported data:
{search_results}

User question: {message}"""
        else:
            enhanced_message = message
        
        messages_list.append({"role": "user", "content": enhanced_message})
        
        # Call Chat Completions API
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages_list
            )
            
            # Extract response content
            response_text = response.choices[0].message.content
            response_id = response.id
            
            # Build updated conversation history (without the enhanced message for storage)
            updated_history = conversation_history.copy() if conversation_history else []
            updated_history.append({"role": "user", "content": message})
            updated_history.append({"role": "assistant", "content": response_text})
            
            logger.info(f"Successfully sent message using Chat Completions API with vector store search (model: {model})")
            
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
                        return self._send_message_with_vector_store_search(
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
            
            # For other errors, re-raise
            raise
    
    def _send_message_chat_completions_only(
        self,
        message: str,
        instructions: str,
        model: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        user_id: int = None
    ) -> Dict[str, Any]:
        """Send a message using Chat Completions API only (no vector store)."""
            # Build messages list with system instruction and conversation history
            messages_list = [
                {"role": "system", "content": instructions}
            ]
            
            # Add conversation history if provided
            if conversation_history:
                messages_list.extend(conversation_history)
            
            # Add current user message
            messages_list.append({"role": "user", "content": message})
            
        # Call Chat Completions API
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages_list
            )
            
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
                        return self._send_message_chat_completions_only(
                            message=message,
                            instructions=instructions,
                            model=config.DEFAULT_MODEL,
                            conversation_history=conversation_history,
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
