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
    
    def get_or_create_unified_assistant(self, vector_store_id: str) -> Optional[str]:
        """
        Get or create a unified assistant for all plugins.
        
        Args:
            vector_store_id: Unified vector store ID
        
        Returns:
            Assistant ID or None
        """
        if self._unified_assistant_id:
            # Verify assistant still exists and update vector store if needed
            try:
                assistant = self.client.beta.assistants.retrieve(self._unified_assistant_id)
                # Update vector store if it changed
                current_vs_ids = []
                if assistant.tool_resources and assistant.tool_resources.file_search:
                    current_vs_ids = assistant.tool_resources.file_search.vector_store_ids or []
                
                if [vector_store_id] != current_vs_ids:
                    # Update assistant with new vector store
                    assistant = self.client.beta.assistants.update(
                        assistant.id,
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
                if assistant.name == "vector_infinity_unified":
                    logger.info(f"Found existing unified assistant: {assistant.id}")
                    # Update vector store
                    assistant = self.client.beta.assistants.update(
                        assistant.id,
                        tool_resources={
                            "file_search": {
                                "vector_store_ids": [vector_store_id]
                            }
                        }
                    )
                    self._unified_assistant_id = assistant.id
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
                name="vector_infinity_unified",
                instructions="You are a helpful assistant that can answer questions about all imported data from various sources (Gmail, WhatsApp, WHOOP, etc.). Use the provided context from the vector store to answer questions accurately. When answering, mention the source of the information when relevant.",
                model="gpt-4o-mini",  # Use gpt-4o-mini for cost efficiency
                tools=[{"type": "file_search"}],
                tool_resources=tool_resources
            )
            logger.info(f"Created new unified assistant: {assistant.id}")
            self._unified_assistant_id = assistant.id
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

