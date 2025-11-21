"""Service for managing Gemini 3 conversations with File Search Tool (RAG)."""
import os
import logging
from typing import Optional, List, Dict, Any
from google import genai
from google.genai import types
from database import UserSettings, ChatThread, SessionLocal
from file_search_service import FileSearchService
import config

logger = logging.getLogger(__name__)

DEFAULT_INSTRUCTIONS = """You are a helpful assistant with access to a File Search Tool that can search through imported user data (emails, WhatsApp messages, WHOOP health data, GitHub files, etc.).

IMPORTANT: When the user asks questions about their data, you MUST use the File Search Tool to search for relevant information. The tool will automatically search through all imported data when you use it.

Instructions:
- ALWAYS use the File Search Tool when users ask about their emails, messages, health data, or any imported information
- Search comprehensively - the tool can access thousands of items
- Provide detailed insights based on what you find in the search results
- If you find relevant information, cite it naturally (e.g., "Based on your emails..." or "From your data...")
- If no relevant information is found after searching, you can use your general knowledge
- Be thorough and analytical when answering questions about the user's data"""


class ChatService:
    """Service for managing Gemini 3 conversations with context retrieval."""
    
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required")
        self.client = genai.Client(api_key=api_key)
        self.file_search_service = FileSearchService()
    
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
            return "gemini-3-pro-preview"
        
        db = SessionLocal()
        try:
            settings = db.query(UserSettings).filter(UserSettings.user_id == user_id).first()
            if settings and settings.assistant_model:
                # Check if it's a Gemini model
                if settings.assistant_model.startswith("gemini-"):
                    logger.debug(f"Using user-selected model: {settings.assistant_model} for user {user_id}")
                    return settings.assistant_model
            return "gemini-3-pro-preview"
        finally:
            db.close()
    
    def _get_thinking_level(self, user_id: int = None) -> str:
        """Get thinking level for Gemini 3 (low or high)."""
        # Default to high for better reasoning, can be made configurable later
        return "high"
    
    def send_message(
        self, 
        message: str, 
        thread_id: Optional[str] = None,
        vector_store_id: Optional[str] = None,  # Deprecated, not used
        user_id: int = None,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        Send a message using Gemini 3 with context retrieval.
        
        Args:
            message: User message
            thread_id: Thread ID (for conversation continuity, stored in database)
            vector_store_id: Deprecated parameter, not used
            user_id: User ID for user-specific settings
            conversation_history: Previous conversation messages (optional)
        
        Returns:
            Dictionary with:
            - response_id: Thread ID (for tracking)
            - content: AI response text
            - openai_thread_id: Thread ID (stored in openai_thread_id field for database compatibility)
            - messages: Updated conversation history
        """
        if not user_id:
            raise ValueError("user_id is required")
        
        model = self._get_model(user_id)
        instructions = self._get_instructions(user_id)
        thinking_level = self._get_thinking_level(user_id)
        
        # Get conversation history from database if thread exists and not provided
        if conversation_history is None:
            conversation_history = []
            if thread_id:
                db = SessionLocal()
                try:
                    chat_thread = db.query(ChatThread).filter(
                        ChatThread.openai_thread_id == thread_id,  # Reusing field name for compatibility
                        ChatThread.user_id == user_id
                    ).first()
                    if chat_thread and chat_thread.conversation_history:
                        conversation_history = chat_thread.conversation_history
                finally:
                    db.close()
        
        # Get file search store name for this user
        file_search_store_name = self.file_search_service.get_unified_file_search_store_name(user_id=user_id)
        
        # Build conversation contents for Gemini
        contents = []
        
        # Add system instructions as first user message (Gemini doesn't have separate system messages)
        if instructions:
            contents.append({
                "role": "user",
                "parts": [{"text": instructions}]
            })
            contents.append({
                "role": "model",
                "parts": [{"text": "I understand. I'll use the File Search Tool to find relevant information from your imported data to answer questions accurately."}]
            })
        
        # Add conversation history
        for msg in conversation_history:
            if msg.get("role") == "user":
                contents.append({
                    "role": "user",
                    "parts": [{"text": msg.get("content", "")}]
                })
            elif msg.get("role") == "assistant":
                contents.append({
                    "role": "model",
                    "parts": [{"text": msg.get("content", "")}]
                })
        
        # Add current user message
        # If File Search Tool is available, explicitly prompt to use it for data-related questions
        user_message = message
        if file_search_store_name:
            # Check if the message seems to be asking about user's data
            data_keywords = ["my", "me", "my emails", "my messages", "my data", "tell me about", "what can you", "analyze", "insights", "summary"]
            message_lower = message.lower()
            if any(keyword in message_lower for keyword in data_keywords):
                # Add explicit instruction to use File Search Tool
                user_message = f"{message}\n\n[Use the File Search Tool to search through all imported data to answer this question comprehensively.]"
                logger.info(f"Added explicit File Search Tool prompt for data-related question")
        
        contents.append({
            "role": "user",
            "parts": [{"text": user_message}]
        })
        
        # Generate response with File Search Tool
        try:
            # Build generation config with File Search Tool if store exists
            # Add File Search Tool if store exists
            tools = None
            if file_search_store_name:
                tools = [
                    types.Tool(
                        file_search=types.FileSearch(
                            file_search_store_names=[file_search_store_name]
                        )
                    )
                ]
                logger.info(f"Using File Search Tool with store: {file_search_store_name}")
                # Log that we're expecting the tool to be used
                if "my" in message.lower() or "tell me" in message.lower() or "what can you" in message.lower():
                    logger.info(f"Question appears to be about user data - File Search Tool should be invoked")
            
            # Generate content using the new SDK with File Search Tool
            response = self.client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=1.0,  # Gemini 3 default
                    tools=tools if tools else None
                )
            )
            
            # Extract response text
            if hasattr(response, 'text'):
                response_text = response.text
            elif hasattr(response, 'candidates') and response.candidates:
                # Fallback: try to get text from candidates
                candidate = response.candidates[0]
                if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                    response_text = candidate.content.parts[0].text if candidate.content.parts else str(response)
                else:
                    response_text = str(response)
            else:
                response_text = str(response)
            
            # Update conversation history
            updated_history = conversation_history + [
                {"role": "user", "content": message},
                {"role": "assistant", "content": response_text}
            ]
            
            logger.info(f"Successfully sent message using Gemini 3 (model: {model}, thread: {thread_id})")
            
            return {
                "response_id": thread_id or "gemini_thread",
                "content": response_text,
                "openai_thread_id": thread_id,  # Store in openai_thread_id field for database compatibility
                "messages": updated_history
            }
            
        except Exception as e:
            logger.error(f"Error generating response with Gemini 3: {e}", exc_info=True)
            raise Exception(f"Failed to generate response: {str(e)}")
