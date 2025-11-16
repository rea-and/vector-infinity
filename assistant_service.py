"""Service for managing OpenAI Assistants and chat."""
import os
import logging
from typing import Optional, List, Dict, Any
from openai import OpenAI

logger = logging.getLogger(__name__)


class AssistantService:
    """Service for managing OpenAI Assistants and chat threads."""
    
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")
        self.client = OpenAI(api_key=api_key)
        self._unified_assistant_id = None  # Cache unified assistant ID
    
    def get_or_create_unified_assistant(self, vector_store_id: str, user_id: int = None) -> Optional[str]:
        """
        Get or create a unified assistant for all plugins (user-specific).
        
        Args:
            vector_store_id: Unified vector store ID
            user_id: User ID for user-specific assistant
        
        Returns:
            Assistant ID or None
        """
        cache_key = f"user_{user_id}" if user_id else "default"
        cached_id = getattr(self, f'_unified_assistant_id_{cache_key}', None)
        if cached_id:
            # Verify assistant still exists and update vector store if needed
            try:
                assistant = self.client.beta.assistants.retrieve(cached_id)
                # Update vector store if it changed
                current_vs_ids = []
                if assistant.tool_resources and assistant.tool_resources.file_search:
                    current_vs_ids = assistant.tool_resources.file_search.vector_store_ids or []
                
                if [vector_store_id] != current_vs_ids:
                    # Update assistant with new vector store and instructions
                    assistant = self.client.beta.assistants.update(
                        assistant.id,
                        instructions="You are a helpful assistant that can answer questions using both your general knowledge and any relevant context from imported data (Gmail, WhatsApp, WHOOP, etc.). Answer questions naturally and directly. If you find relevant information in the imported data, mention the source when helpful. If the question is about general topics not covered in the imported data, answer using your general knowledge without mentioning that the information wasn't found in the files. Be concise and helpful.",
                        tool_resources={
                            "file_search": {
                                "vector_store_ids": [vector_store_id]
                            }
                        }
                    )
                    logger.info(f"Updated unified assistant {assistant.id} with new vector store")
                
                return assistant.id
            except Exception as e:
                logger.warning(f"Error retrieving unified assistant: {e}, creating new one")
                # Fall through to create new assistant
        
        # Try to find existing unified assistant by name
        try:
            assistants = self.client.beta.assistants.list(limit=100)
            for assistant in assistants.data:
                assistant_name = f"vector_infinity_unified_user_{user_id}" if user_id else "vector_infinity_unified"
                if assistant.name == assistant_name:
                    logger.info(f"Found existing unified assistant for user {user_id}: {assistant.id}")
                    # Update vector store and instructions
                    assistant = self.client.beta.assistants.update(
                        assistant.id,
                        instructions="You are a helpful assistant that can answer questions using both your general knowledge and any relevant context from imported data (Gmail, WhatsApp, WHOOP, etc.). Answer questions naturally and directly. If you find relevant information in the imported data, mention the source when helpful. If the question is about general topics not covered in the imported data, answer using your general knowledge without mentioning that the information wasn't found in the files. Be concise and helpful.",
                        tool_resources={
                            "file_search": {
                                "vector_store_ids": [vector_store_id]
                            }
                        }
                    )
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
            
            assistant = self.client.beta.assistants.create(
                name=assistant_name,
                instructions="You are a helpful assistant that can answer questions using both your general knowledge and any relevant context from imported data (Gmail, WhatsApp, WHOOP, etc.). Answer questions naturally and directly. If you find relevant information in the imported data, mention the source when helpful. If the question is about general topics not covered in the imported data, answer using your general knowledge without mentioning that the information wasn't found in the files. Be concise and helpful.",
                model="gpt-4o-mini",  # Use gpt-4o-mini for cost efficiency
                tools=[{"type": "file_search"}],
                tool_resources=tool_resources
            )
            logger.info(f"Created new unified assistant for user {user_id}: {assistant.id}")
            setattr(self, f'_unified_assistant_id_{cache_key}', assistant.id)
            return assistant.id
        except Exception as e:
            logger.error(f"Error creating unified assistant: {e}")
            return None
    
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

