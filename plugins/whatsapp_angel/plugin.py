"""WhatsApp Angel plugin."""
from plugin_base import DataSourcePlugin
from datetime import datetime
from pathlib import Path
import logging
import zipfile
import tempfile
import re
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class Plugin(DataSourcePlugin):
    """WhatsApp Angel chat history plugin."""
    
    def __init__(self):
        super().__init__("whatsapp_angel")
        self._uploaded_file_path = None
    
    def set_uploaded_file(self, file_path: str):
        """Set the path to the uploaded zip file."""
        self._uploaded_file_path = file_path
        logger.info(f"Plugin {self.plugin_name}: Set uploaded file path to {file_path}")
    
    @property
    def uploaded_file_path(self):
        """Get the uploaded file path."""
        return self._uploaded_file_path
    
    def fetch_data(self) -> List[Dict[str, Any]]:
        """Parse WhatsApp chat from uploaded zip file."""
        if not self._uploaded_file_path:
            raise Exception("No file uploaded. Please upload a zip file containing the chat export.")
        
        logger.info(f"Starting WhatsApp chat import from: {self._uploaded_file_path}")
        
        # Check if file exists
        if not Path(self._uploaded_file_path).exists():
            raise Exception(f"Uploaded file not found: {self._uploaded_file_path}")
        
        logger.info(f"Uploaded file exists, size: {Path(self._uploaded_file_path).stat().st_size} bytes")
        
        results = []
        
        try:
            # Extract zip file
            logger.info("Extracting ZIP file...")
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                logger.info(f"Using temporary directory: {temp_path}")
                
                with zipfile.ZipFile(self._uploaded_file_path, 'r') as zip_ref:
                    file_list = zip_ref.namelist()
                    logger.info(f"ZIP file contains {len(file_list)} files: {file_list}")
                    zip_ref.extractall(temp_path)
                    logger.info("ZIP extraction completed")
                
                # Find the txt file (WhatsApp exports are usually named like "WhatsApp Chat with Angel.txt")
                txt_files = list(temp_path.glob("*.txt"))
                logger.info(f"Found {len(txt_files)} .txt file(s) in extracted archive")
                
                if not txt_files:
                    # List all files in temp directory for debugging
                    all_files = list(temp_path.glob("*"))
                    logger.error(f"No .txt files found. All files in archive: {[f.name for f in all_files]}")
                    raise Exception("No .txt file found in the zip archive")
                
                chat_file = txt_files[0]
                logger.info(f"Using chat file: {chat_file.name} (size: {chat_file.stat().st_size} bytes)")
                
                # Parse WhatsApp chat format
                # Format: [DD/MM/YYYY, HH:MM:SS] Sender: Message
                # Example: [14/11/2024, 10:30:45] Andrea: Hello!
                
                logger.info("Reading chat file content...")
                with open(chat_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                logger.info(f"Chat file read successfully. Content length: {len(content)} characters")
                logger.info(f"First 500 characters of file:\n{content[:500]}")
                
                # Split into messages
                # Pattern: [date, time] sender: message
                pattern = r'\[(\d{1,2}/\d{1,2}/\d{4}),\s*(\d{1,2}:\d{2}:\d{2})\]\s*([^:]+):\s*(.*?)(?=\[\d{1,2}/\d{1,2}/\d{4}|\Z)'
                
                logger.info(f"Searching for messages with pattern: {pattern}")
                messages = re.finditer(pattern, content, re.DOTALL | re.MULTILINE)
                
                # Convert to list to count
                message_list = list(messages)
                logger.info(f"Regex found {len(message_list)} potential messages")
                
                if len(message_list) == 0:
                    # Try to find any lines that look like messages
                    lines = content.split('\n')
                    logger.info(f"File has {len(lines)} total lines")
                    # Show first 20 lines for debugging
                    logger.info(f"First 20 lines of file:\n{chr(10).join(lines[:20])}")
                    
                    # Try alternative patterns
                    alt_patterns = [
                        r'\[(\d{1,2}/\d{1,2}/\d{4}),\s*(\d{1,2}:\d{2}:\d{2})\]\s*([^:]+):\s*(.*)',
                        r'(\d{1,2}/\d{1,2}/\d{4}),\s*(\d{1,2}:\d{2}:\d{2})\s*-\s*([^:]+):\s*(.*)',
                        r'\[(\d{1,2}\.\d{1,2}\.\d{4}),\s*(\d{1,2}:\d{2}:\d{2})\]\s*([^:]+):\s*(.*)',
                    ]
                    
                    for i, alt_pattern in enumerate(alt_patterns):
                        logger.info(f"Trying alternative pattern {i+1}: {alt_pattern}")
                        alt_messages = re.finditer(alt_pattern, content, re.DOTALL | re.MULTILINE)
                        alt_list = list(alt_messages)
                        if alt_list:
                            logger.info(f"Alternative pattern {i+1} found {len(alt_list)} messages!")
                            message_list = alt_list
                            pattern = alt_pattern
                            break
                
                message_count = 0
                for match in message_list:
                    date_str = match.group(1)
                    time_str = match.group(2)
                    sender = match.group(3).strip()
                    message = match.group(4).strip()
                    
                    # Skip empty messages
                    if not message:
                        continue
                    
                    # Parse timestamp
                    try:
                        # WhatsApp format: DD/MM/YYYY, HH:MM:SS
                        datetime_str = f"{date_str} {time_str}"
                        source_timestamp = datetime.strptime(datetime_str, "%d/%m/%Y %H:%M:%S")
                    except ValueError:
                        # Try alternative format if needed
                        try:
                            source_timestamp = datetime.strptime(datetime_str, "%m/%d/%Y %H:%M:%S")
                        except ValueError:
                            logger.warning(f"Could not parse timestamp: {datetime_str}, using current time")
                            source_timestamp = datetime.now()
                    
                    # Create unique source_id from timestamp and message hash
                    source_id = f"{source_timestamp.isoformat()}_{hash(message) % 1000000}"
                    
                    results.append({
                        "source_id": source_id,
                        "item_type": "whatsapp_message",
                        "title": f"Message from {sender}",
                        "content": message,
                        "metadata": {
                            "sender": sender,
                            "date": date_str,
                            "time": time_str
                        },
                        "source_timestamp": source_timestamp
                    })
                    
                    message_count += 1
                    if message_count <= 5:
                        logger.debug(f"Sample message {message_count}: sender={sender}, date={date_str}, time={time_str}, message_preview={message[:50]}...")
                
                logger.info(f"Successfully parsed {message_count} messages from WhatsApp chat")
                
                if message_count == 0:
                    logger.warning("No messages were parsed. This might indicate a format mismatch.")
                    logger.warning("Please check the chat export format. Expected format: [DD/MM/YYYY, HH:MM:SS] Sender: Message")
                
        except Exception as e:
            logger.error(f"Error parsing WhatsApp chat: {e}", exc_info=True)
            raise Exception(f"Error parsing WhatsApp chat: {str(e)}")
        
        return results
    
    def test_connection(self) -> bool:
        """Test if a file has been uploaded."""
        return self._uploaded_file_path is not None and Path(self._uploaded_file_path).exists()
    
    def get_config_schema(self) -> Dict[str, Any]:
        """Return configuration schema."""
        schema = super().get_config_schema()
        return schema

