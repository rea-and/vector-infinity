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
                # Return the user's selected model even if not in AVAILABLE_MODELS
                # (AVAILABLE_MODELS is just for the UI dropdown - user may have selected
                # a model that was later removed from the list, or a model not in the default list)
                # We'll validate it works when actually calling the API
                logger.debug(f"Using user-selected model: {settings.assistant_model} for user {user_id}")
                return settings.assistant_model
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
        # Both APIs now support tool_resources with vector_store_ids
        use_responses_api = responses_api_available and (requires_responses or previous_response_id is not None)
        
        if use_responses_api:
            try:
                return self._send_message_responses_api(
                    message=message,
                    instructions=instructions,
                    model=model,
                    vector_store_id=vector_store_id,
                    previous_response_id=previous_response_id,
                    conversation_history=conversation_history
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
        previous_response_id: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None
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
        # Note: previous_response_id must be from Responses API, not Chat Completions
        # If it's from Chat Completions (starts with 'chatcmpl-'), don't use it
        if previous_response_id:
            if previous_response_id.startswith('chatcmpl-'):
                # This is a Chat Completions response ID, not compatible with Responses API
                logger.warning(f"previous_response_id is from Chat Completions ({previous_response_id}), not using it for Responses API")
            else:
                request_params["previous_response_id"] = previous_response_id
                logger.info(f"Using previous_response_id for state management: {previous_response_id}")
        
        # Add vector store for file search if provided
        # According to OpenAI Python library: https://github.com/openai/openai-python
        # Responses API uses 'tools' parameter with vector_store_ids inside the tool object
        # - tools: [{"type": "file_search", "vector_store_ids": [...]}]
        if vector_store_id:
            request_params["tools"] = [{
                "type": "file_search",
                "vector_store_ids": [vector_store_id]
            }]
            logger.info(f"Using vector store {vector_store_id} for file search via tools (Responses API)")
        
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
            # Log the full error details for debugging
            error_str = str(api_error)
            logger.error(f"Responses API error: {api_error}")
            logger.error(f"Responses API error type: {type(api_error)}")
            
            # Check if the error is about file_search not being supported
            # Some models (like gpt-5.1-codex-mini) don't support file_search tool
            if "file_search" in error_str.lower() and "not supported" in error_str.lower():
                logger.warning(f"Model {model} does not support file_search tool in Responses API. Trying Assistants API as fallback...")
                # Fall back to Assistants API which supports vector stores natively
                try:
                    return self._send_message_assistants_api_fallback(
                        message=message,
                        instructions=instructions,
                        model=model,
                        vector_store_id=vector_store_id,
                        conversation_history=conversation_history
                    )
                except Exception as assistants_error:
                    logger.warning(f"Assistants API fallback also failed: {assistants_error}")
                    # If Assistants API also fails, try Chat Completions with tools parameter
                    logger.warning(f"Trying Chat Completions API with tools parameter...")
                    try:
                        messages_list = [
                            {"role": "system", "content": instructions}
                        ]
                        if conversation_history:
                            messages_list.extend(conversation_history)
                        messages_list.append({"role": "user", "content": message})
                        
                        chat_params = {
                            "model": model,
                            "messages": messages_list,
                            "tools": [{
                                "type": "file_search",
                                "vector_store_ids": [vector_store_id]
                            }]
                        }
                        logger.info(f"Trying Chat Completions API with tools for vector store {vector_store_id}")
                        chat_response = self.client.chat.completions.create(**chat_params)
                        
                        response_text = chat_response.choices[0].message.content
                        response_id = chat_response.id
                        
                        logger.info(f"Successfully used Chat Completions API with tools (model {model} doesn't support file_search in Responses API)")
                        
                        return {
                            "response_id": response_id,
                            "content": response_text,
                            "messages": messages_list + [{"role": "assistant", "content": response_text}]
                        }
                    except Exception as chat_error:
                        error_str_chat = str(chat_error)
                        logger.warning(f"Chat Completions with tools also failed: {chat_error}")
                        # If tools also doesn't work, try without vector store
                        if "file_search" in error_str_chat.lower() or "not supported" in error_str_chat.lower():
                            logger.warning(f"Model {model} does not support file_search at all. Retrying without vector store...")
                            # Retry without file_search tool
                            request_params_no_file_search = request_params.copy()
                            if "tools" in request_params_no_file_search:
                                del request_params_no_file_search["tools"]
                            
                            try:
                                if hasattr(self.client, 'responses'):
                                    response = self.client.responses.create(**request_params_no_file_search)
                                elif hasattr(self.client, 'beta') and hasattr(self.client.beta, 'responses'):
                                    response = self.client.beta.responses.create(**request_params_no_file_search)
                                else:
                                    raise AttributeError("Responses API not available in this OpenAI client version")
                                logger.info(f"Successfully sent message without file_search tool (model {model} doesn't support it)")
                                # Continue to extract response below
                            except Exception as retry_error:
                                logger.error(f"Responses API failed even without file_search: {retry_error}")
                                # Re-raise to be handled by caller
                                raise
                        else:
                            # Some other error with Chat Completions, re-raise
                            raise
            else:
                # For other errors, log and re-raise
                if hasattr(api_error, 'response'):
                    try:
                        error_response = api_error.response
                        logger.error(f"Responses API error response: {error_response}")
                        if hasattr(error_response, 'text'):
                            logger.error(f"Responses API error response text: {error_response.text}")
                    except:
                        pass
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
        # Based on the actual response structure, try output_text first, then output, then text
        if hasattr(response, 'output_text') and response.output_text:
            # Responses API uses 'output_text' field (string)
            response_text = response.output_text
        elif hasattr(response, 'output') and response.output:
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
        elif hasattr(response, 'text') and response.text:
            # Direct text field
            response_text = response.text
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
        # Note: Chat Completions API may not support file_search in all Python SDK versions
        # Try using tools parameter similar to Responses API
        if vector_store_id:
            request_params["tools"] = [{
                "type": "file_search",
                "vector_store_ids": [vector_store_id]
            }]
            logger.info(f"Using vector store {vector_store_id} for file search via tools (Chat Completions API)")
            
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
            # Check if it's an unsupported model error or file_search not supported
            error_str = str(e)
            
            # Check if file_search is not supported (try without it)
            if ("file_search" in error_str.lower() and "not supported" in error_str.lower()) or \
               ("unexpected keyword argument" in error_str.lower() and "tools" in error_str.lower()):
                logger.warning(f"Chat Completions API doesn't support file_search for model {model}. Retrying without file_search...")
                # Retry without file_search
                request_params_no_file_search = request_params.copy()
                if "tools" in request_params_no_file_search:
                    del request_params_no_file_search["tools"]
                
                try:
                    response = self.client.chat.completions.create(**request_params_no_file_search)
                    response_text = response.choices[0].message.content
                    response_id = response.id
                    
                    updated_history = conversation_history.copy() if conversation_history else []
                    updated_history.append({"role": "user", "content": message})
                    updated_history.append({"role": "assistant", "content": response_text})
                    
                    logger.info(f"Successfully sent message without file_search (Chat Completions API)")
                    return {
                        "response_id": response_id,
                        "content": response_text,
                        "messages": updated_history
                    }
                except Exception as retry_error:
                    logger.error(f"Chat Completions API failed even without file_search: {retry_error}")
                    # Continue to other error handling below
            
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
                        previous_response_id=None,
                        conversation_history=conversation_history
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
    
    def _send_message_assistants_api_fallback(
        self,
        message: str,
        instructions: str,
        model: str,
        vector_store_id: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """Fallback to Assistants API when file_search is not supported in Responses/Chat Completions APIs."""
        import uuid
        
        # Create a temporary assistant with the vector store
        assistant = self.client.beta.assistants.create(
            name=f"Temp Assistant {uuid.uuid4().hex[:8]}",
            instructions=instructions,
            model=model,
            tool_resources={
                "file_search": {
                    "vector_store_ids": [vector_store_id]
                }
            } if vector_store_id else None,
            tools=[{"type": "file_search"}] if vector_store_id else []
        )
        
        try:
            # Create a thread
            thread = self.client.beta.threads.create()
            
            try:
                # Add conversation history as messages
                if conversation_history:
                    for msg in conversation_history:
                        if msg.get("role") == "user":
                            self.client.beta.threads.messages.create(
                                thread_id=thread.id,
                                role="user",
                                content=msg.get("content", "")
                            )
                        elif msg.get("role") == "assistant":
                            self.client.beta.threads.messages.create(
                                thread_id=thread.id,
                                role="assistant",
                                content=msg.get("content", "")
                            )
                
                # Add current message
                self.client.beta.threads.messages.create(
                    thread_id=thread.id,
                    role="user",
                    content=message
                )
                
                # Run the assistant
                run = self.client.beta.threads.runs.create(
                    thread_id=thread.id,
                    assistant_id=assistant.id
                )
                
                # Wait for completion
                import time
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
                
                # Get the response
                messages = self.client.beta.threads.messages.list(
                    thread_id=thread.id,
                    order="asc"
                )
                
                # Find the assistant's response (last message from assistant)
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
                
                # Build conversation history
                updated_history = conversation_history.copy() if conversation_history else []
                updated_history.append({"role": "user", "content": message})
                updated_history.append({"role": "assistant", "content": response_text})
                
                logger.info(f"Successfully used Assistants API fallback (model {model} doesn't support file_search in Responses API)")
                
                return {
                    "response_id": run.id,
                    "content": response_text,
                    "messages": updated_history
                }
            finally:
                # Clean up thread
                try:
                    self.client.beta.threads.delete(thread.id)
                except:
                    pass
        finally:
            # Clean up assistant
            try:
                self.client.beta.assistants.delete(assistant.id)
            except:
                pass

