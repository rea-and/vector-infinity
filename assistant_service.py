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
        self._assistant_cache = {}  # Cache assistant IDs per plugin
    
    def get_or_create_assistant(self, plugin_name: str, vector_store_ids: List[str]) -> Optional[str]:
        """
        Get or create an assistant for a plugin.
        
        Args:
            plugin_name: Name of the plugin
            vector_store_ids: List of vector store IDs to attach to the assistant
        
        Returns:
            Assistant ID or None
        """
        if plugin_name in self._assistant_cache:
            # Verify assistant still exists and update vector stores if needed
            try:
                assistant = self.client.beta.assistants.retrieve(self._assistant_cache[plugin_name])
                # Update vector stores if they changed
                current_vs_ids = []
                if assistant.tool_resources and assistant.tool_resources.file_search:
                    current_vs_ids = assistant.tool_resources.file_search.vector_store_ids or []
                
                if set(current_vs_ids) != set(vector_store_ids):
                    # Update assistant with new vector stores
                    assistant = self.client.beta.assistants.update(
                        assistant.id,
                        tool_resources={
                            "file_search": {
                                "vector_store_ids": vector_store_ids
                            }
                        }
                    )
                    logger.info(f"Updated assistant {assistant.id} with new vector stores")
                
                return assistant.id
            except Exception as e:
                logger.warning(f"Error retrieving assistant: {e}, creating new one")
                # Fall through to create new assistant
        
        # Try to find existing assistant by name
        try:
            assistants = self.client.beta.assistants.list(limit=100)
            for assistant in assistants.data:
                if assistant.name == f"vector_infinity_{plugin_name}":
                    logger.info(f"Found existing assistant for {plugin_name}: {assistant.id}")
                    # Update vector stores
                    if vector_store_ids:
                        assistant = self.client.beta.assistants.update(
                            assistant.id,
                            tool_resources={
                                "file_search": {
                                    "vector_store_ids": vector_store_ids
                                }
                            }
                        )
                    self._assistant_cache[plugin_name] = assistant.id
                    return assistant.id
        except Exception as e:
            logger.warning(f"Error listing assistants: {e}")
        
        # Create new assistant
        try:
            tool_resources = None
            if vector_store_ids:
                tool_resources = {
                    "file_search": {
                        "vector_store_ids": vector_store_ids
                    }
                }
            
            assistant = self.client.beta.assistants.create(
                name=f"vector_infinity_{plugin_name}",
                instructions=f"You are a helpful assistant that can answer questions about {plugin_name} data. Use the provided context from the vector store to answer questions accurately.",
                model="gpt-4o-mini",  # Use gpt-4o-mini for cost efficiency
                tools=[{"type": "file_search"}],
                tool_resources=tool_resources
            )
            logger.info(f"Created new assistant for {plugin_name}: {assistant.id}")
            self._assistant_cache[plugin_name] = assistant.id
            return assistant.id
        except Exception as e:
            logger.error(f"Error creating assistant for {plugin_name}: {e}")
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

