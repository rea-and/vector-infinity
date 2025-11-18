"""Service for managing OpenAI Responses API conversations with fallback to Chat Completions."""
import os
import logging
from typing import Optional, List, Dict, Any
from openai import OpenAI
from database import UserSettings, SessionLocal
import config

logger = logging.getLogger(__name__)

DEFAULT_INSTRUCTIONS = "You are a helpful assistant that can answer questions using both your general knowledge and any relevant context from imported data (Gmail, WhatsApp, WHOOP, etc.). Answer questions naturally and directly. If you find relevant information in the imported data, mention the source when helpful. If the question is about general topics not covered in the imported data, answer using your general knowledge without mentioning that the information wasn't found in the files. Be concise and helpful."


class ChatService:
    """Service for managing OpenAI Responses API conversations with fallback to Chat Completions."""
    
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")
        self.client = OpenAI(api_key=api_key)
        self._responses_api_available = None  # Cache for Responses API availability check
    
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
    
    def _is_responses_api_available(self) -> bool:
        """Check if Responses API is available in the OpenAI client."""
        if self._responses_api_available is not None:
            return self._responses_api_available
        
        # Check if Responses API is available
        try:
            if hasattr(self.client, 'responses'):
                self._responses_api_available = True
                return True
            elif hasattr(self.client, 'beta') and hasattr(self.client.beta, 'responses'):
                self._responses_api_available = True
                return True
            else:
                self._responses_api_available = False
                return False
        except Exception:
            self._responses_api_available = False
            return False
    
    def _requires_responses_api(self, model: str) -> bool:
        """Check if a model requires Responses API (newer models that don't work with Chat Completions)."""
        # Models that are known to require Responses API
        responses_only_models = [
            "gpt-5.1-codex-mini",
            "gpt-5.1",
            "gpt-5",
            "o4-mini",
            "o4"
        ]
        return any(model.startswith(prefix) for prefix in responses_only_models)
    
    def send_message(
        self, 
        message: str, 
        conversation_history: Optional[List[Dict[str, str]]] = None,
        vector_store_id: Optional[str] = None,
        user_id: int = None,
        previous_response_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send a message using Responses API (preferred) with fallback to Chat Completions API.
        
        Args:
            message: User message
            conversation_history: Previous conversation messages (for Chat Completions fallback)
            vector_store_id: Vector store ID for file search
            user_id: User ID for user-specific settings
            previous_response_id: Previous response ID for Responses API state management
        
        Returns:
            Dictionary with:
            - response_id: Response ID (for tracking and state management)
            - content: AI response text
            - messages: Updated conversation history (for Chat Completions fallback)
        """
        instructions = self._get_instructions(user_id)
        model = self._get_model(user_id)
        
        # Determine which API to use
        responses_api_available = self._is_responses_api_available()
        requires_responses = self._requires_responses_api(model)
        
        # Use Responses API if:
        # 1. It's available AND
        # 2. (The model requires it OR we have a previous_response_id for state management)
        # Note: Vector store support in Responses API is being tested - if it fails, we'll fall back
        use_responses_api = responses_api_available and (requires_responses or previous_response_id is not None)
        
        if use_responses_api:
            try:
                return self._send_message_responses_api(
                    message=message,
                    instructions=instructions,
                    model=model,
                    vector_store_id=vector_store_id,
                    previous_response_id=previous_response_id
                )
            except Exception as responses_error:
                error_str = str(responses_error)
                logger.debug(f"Responses API failed: {responses_error}")
                
                # If model requires Responses API but it failed, try Chat Completions as fallback
                # (might work for some models)
                if requires_responses:
                    logger.warning(f"Model {model} requires Responses API but it failed. Trying Chat Completions as fallback...")
                    return self._send_message_chat_completions_api(
                        message=message,
                        instructions=instructions,
                        model=model,
                        conversation_history=conversation_history,
                        vector_store_id=vector_store_id,
                        user_id=user_id
                    )
                else:
                    # For models that don't require Responses API, fall back silently
                    logger.debug(f"Falling back to Chat Completions API for model {model}")
                    return self._send_message_chat_completions_api(
                        message=message,
                        instructions=instructions,
                        model=model,
                        conversation_history=conversation_history,
                        vector_store_id=vector_store_id,
                        user_id=user_id
                    )
        else:
            # Use Chat Completions API directly (Responses API not available or not needed)
            if not responses_api_available and requires_responses:
                logger.warning(f"Model {model} requires Responses API but it's not available in this client version. Using Chat Completions (may fail).")
            return self._send_message_chat_completions_api(
                message=message,
                instructions=instructions,
                model=model,
                conversation_history=conversation_history,
                vector_store_id=vector_store_id,
                user_id=user_id
            )
    
    def _send_message_responses_api(
        self,
        message: str,
        instructions: str,
        model: str,
        vector_store_id: Optional[str] = None,
        previous_response_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send a message using Responses API (stateful, supports newer models)."""
        # Build request parameters for Responses API
        # Responses API uses 'input' for user message and 'instructions' for system prompt
        request_params = {
            "model": model,
            "input": message,
            "instructions": instructions
        }
        
        # Add previous_response_id for state management (if this is a continuation)
        if previous_response_id:
            request_params["previous_response_id"] = previous_response_id
            logger.info(f"Using previous_response_id for state management: {previous_response_id}")
        
        # Note: Vector store support in Responses API may be different
        # For now, we'll try without vector stores and see if the API supports them
        # If vector stores are needed, we may need to use a different approach
        if vector_store_id:
            # Try different possible parameter names for vector stores
            # The Responses API might not support vector stores yet, or use a different structure
            logger.warning(f"Vector store {vector_store_id} requested but Responses API vector store support is not yet implemented")
            # TODO: Implement vector store support for Responses API when available
        
        # Call Responses API
        # Note: The Responses API endpoint might be client.responses.create() or client.beta.responses.create()
        # Try both to handle different client versions
        response = None
        try:
            # Try client.responses.create() first (newer API structure)
            if hasattr(self.client, 'responses'):
                response = self.client.responses.create(**request_params)
            # Try client.beta.responses.create() (beta API structure)
            elif hasattr(self.client, 'beta') and hasattr(self.client.beta, 'responses'):
                response = self.client.beta.responses.create(**request_params)
            else:
                raise AttributeError("Responses API not available in this OpenAI client version")
        except AttributeError as attr_error:
            # Responses API might not be available in this version of the client
            raise Exception(f"Responses API not available in this OpenAI client version: {attr_error}")
        except Exception as api_error:
            # Re-raise API errors (like model not supported, etc.) to be handled by caller
            raise
        
        # Extract response content
        # Responses API structure may differ from Chat Completions
        # Try different possible response structures
        response_text = None
        response_id = None
        
        # Log the response structure for debugging
        logger.info(f"Responses API response type: {type(response)}")
        logger.info(f"Responses API response attributes: {[attr for attr in dir(response) if not attr.startswith('_')]}")
        
        # Try to get a string representation for debugging
        try:
            response_repr = str(response)[:500]
            logger.info(f"Responses API response repr: {response_repr}")
        except:
            pass
        
        # Try to get response ID first
        if hasattr(response, 'id'):
            response_id = response.id
        elif hasattr(response, 'response_id'):
            response_id = response.response_id
        
        # Try different possible content fields
        if hasattr(response, 'output') and response.output:
            # Responses API might use 'output' field
            if isinstance(response.output, str):
                response_text = response.output
            elif hasattr(response.output, 'content'):
                response_text = response.output.content
            elif hasattr(response.output, 'text'):
                response_text = response.output.text
            elif hasattr(response.output, 'message'):
                if isinstance(response.output.message, str):
                    response_text = response.output.message
                elif hasattr(response.output.message, 'content'):
                    response_text = response.output.message.content
        elif hasattr(response, 'content'):
            if isinstance(response.content, str):
                response_text = response.content
            elif hasattr(response.content, 'text'):
                response_text = response.content.text
        elif hasattr(response, 'text'):
            response_text = response.text
        elif hasattr(response, 'message'):
            if isinstance(response.message, str):
                response_text = response.message
            elif hasattr(response.message, 'content'):
                response_text = response.message.content
        elif hasattr(response, 'choices') and response.choices:
            # Fallback to Chat Completions-like structure
            response_text = response.choices[0].message.content
        elif hasattr(response, 'data'):
            # Try data field
            if isinstance(response.data, str):
                response_text = response.data
            elif hasattr(response.data, 'content'):
                response_text = response.data.content
        
        # If still no content, try to inspect the response object
        if not response_text:
            # Try to convert response to dict and look for common fields
            try:
                if hasattr(response, 'model_dump'):
                    response_dict = response.model_dump()
                elif hasattr(response, 'dict'):
                    response_dict = response.dict()
                elif hasattr(response, '__dict__'):
                    response_dict = response.__dict__
                else:
                    response_dict = {}
                
                logger.debug(f"Responses API response dict keys: {list(response_dict.keys()) if isinstance(response_dict, dict) else 'Not a dict'}")
                
                # Look for common content fields in the dict
                for key in ['output', 'content', 'text', 'message', 'data', 'response']:
                    if key in response_dict and response_dict[key]:
                        if isinstance(response_dict[key], str):
                            response_text = response_dict[key]
                            break
                        elif isinstance(response_dict[key], dict):
                            # Try nested content
                            for nested_key in ['content', 'text', 'message']:
                                if nested_key in response_dict[key] and response_dict[key][nested_key]:
                                    response_text = response_dict[key][nested_key]
                                    break
                            if response_text:
                                break
            except Exception as dict_error:
                logger.debug(f"Error converting response to dict: {dict_error}")
        
        # Last resort: convert to string
        if not response_text:
            response_str = str(response)
            logger.warning(f"Could not extract response content from Responses API response. Response: {response_str[:500]}")
            raise Exception(f"Could not extract response content from Responses API response. Response type: {type(response)}, Response: {str(response)[:200]}")
        
        if not response_id:
            logger.warning("Could not extract response_id from Responses API response")
        
        # For Responses API, we don't need to manage conversation history locally
        # The API handles state via previous_response_id
        # But we still return messages for backward compatibility with the frontend
        updated_history = []
        if previous_response_id:
            # If we have a previous response, we're continuing a conversation
            # The Responses API manages state, but we still need to return messages for the frontend
            # We'll reconstruct from the response if needed, or keep minimal history
            pass
        
        updated_history.append({"role": "user", "content": message})
        updated_history.append({"role": "assistant", "content": response_text})
        
        logger.info(f"Successfully sent message using Responses API (model: {model}, response_id: {response_id})")
        
        return {
            "response_id": response_id,
            "content": response_text,
            "messages": updated_history
        }
    
    def _send_message_chat_completions_api(
        self,
        message: str,
        instructions: str,
        model: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        vector_store_id: Optional[str] = None,
        user_id: int = None
    ) -> Dict[str, Any]:
        """Send a message using Chat Completions API (fallback for older models)."""
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
        # Chat Completions API uses attachments on messages for file search
        if vector_store_id:
            try:
                # Get all file IDs from the vector store (handle pagination)
                file_ids = []
                has_more = True
                after = None
                
                while has_more:
                    params = {"vector_store_id": vector_store_id, "limit": 100}
                    if after:
                        params["after"] = after
                    
                    vector_store_files = self.client.vector_stores.files.list(**params)
                    
                    if hasattr(vector_store_files, 'data') and vector_store_files.data:
                        file_ids.extend([file_item.id for file_item in vector_store_files.data])
                        # Check if there are more pages
                        has_more = hasattr(vector_store_files, 'has_more') and vector_store_files.has_more
                        if has_more and vector_store_files.data:
                            after = vector_store_files.data[-1].id
                        else:
                            has_more = False
                    else:
                        has_more = False
                
                if file_ids:
                    # Attach file IDs to the user message for file search
                    if messages_list and messages_list[-1]["role"] == "user":
                        messages_list[-1]["attachments"] = [
                            {"file_id": file_id, "tools": [{"type": "file_search"}]}
                            for file_id in file_ids
                        ]
                    logger.info(f"Attached {len(file_ids)} files from vector store to chat message")
                else:
                    logger.warning(f"No files found in vector store {vector_store_id}")
            except Exception as vs_error:
                logger.warning(f"Error getting files from vector store {vector_store_id}: {vs_error}. Continuing without file search.")
        
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
            # Check if it's an unsupported model error
            error_str = str(e)
            if ("unsupported_model" in error_str or 
                "cannot be used" in error_str or 
                "only supported in v1/responses" in error_str or
                "not in v1/chat/completions" in error_str):
                
                logger.error(f"Model {model} is not supported by Chat Completions API. Trying Responses API...")
                # Try Responses API as a last resort
                try:
                    return self._send_message_responses_api(
                        message=message,
                        instructions=instructions,
                        model=model,
                        vector_store_id=vector_store_id,
                        previous_response_id=None
                    )
                except Exception as responses_error:
                    logger.error(f"Responses API also failed: {responses_error}")
                    # Fall back to default model
                    if model != config.DEFAULT_MODEL:
                        logger.info(f"Falling back to default model {config.DEFAULT_MODEL}")
                        if user_id:
                            self._clear_invalid_model(user_id, model)
                        return self._send_message_chat_completions_api(
                            message=message,
                            instructions=instructions,
                            model=config.DEFAULT_MODEL,
                            conversation_history=conversation_history,
                            vector_store_id=vector_store_id,
                            user_id=user_id
                        )
                    raise
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

