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
                # Format: DD/MM/YYYY, HH:MM - Sender: Message
                # Example: 4/03/2025, 20:21 - Andrea: Hey Angel
                # Also supports: [DD/MM/YYYY, HH:MM:SS] Sender: Message (older format)
                
                logger.info("Reading chat file content...")
                with open(chat_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                logger.info(f"Chat file read successfully. Content length: {len(content)} characters")
                logger.info(f"First 500 characters of file:\n{content[:500]}")
                
                # Optimized parsing: Split by message boundaries first, then parse each message
                # This is much faster than using regex lookahead on large files
                # Pattern: DD/MM/YYYY, HH:MM - Sender: Message
                # Find all message start positions (dates followed by time and dash)
                message_start_pattern = r'(\d{1,2}/\d{1,2}/\d{4}),\s*(\d{1,2}:\d{2})\s*-\s*'
                
                logger.info("Finding message boundaries...")
                # Find all positions where a new message starts
                starts = []
                for match in re.finditer(message_start_pattern, content):
                    starts.append(match.start())
                
                # If no matches, try alternative format
                if not starts:
                    logger.info("Trying alternative format with brackets...")
                    alt_start_pattern = r'\[(\d{1,2}/\d{1,2}/\d{4}),\s*(\d{1,2}:\d{2}'
                    for match in re.finditer(alt_start_pattern, content):
                        starts.append(match.start())
                
                logger.info(f"Found {len(starts)} message boundaries")
                
                message_list = []
                
                if not starts:
                    logger.warning("No message boundaries found. Trying fallback regex pattern...")
                    # Fallback to original method (slower but works)
                    pattern = r'(\d{1,2}/\d{1,2}/\d{4}),\s*(\d{1,2}:\d{2})\s*-\s*([^:]+):\s*(.*?)(?=\d{1,2}/\d{1,2}/\d{4},\s*\d{1,2}:\d{2}\s*-\s*|\Z)'
                    messages = re.finditer(pattern, content, re.DOTALL | re.MULTILINE)
                    message_list = list(messages)
                    logger.info(f"Fallback pattern found {len(message_list)} messages")
                else:
                    # Optimized: Process messages using boundaries (much faster - no lookahead)
                    # Add end position for easier slicing
                    starts.append(len(content))
                    
                    # Message parsing pattern (without expensive lookahead)
                    msg_pattern = r'(\d{1,2}/\d{1,2}/\d{4}),\s*(\d{1,2}:\d{2})\s*-\s*([^:]+):\s*(.*)'
                    bracket_pattern = r'\[(\d{1,2}/\d{1,2}/\d{4}),\s*(\d{1,2}:\d{2}:\d{2})\]\s*([^:]+):\s*(.*)'
                    
                    logger.info("Parsing messages from boundaries...")
                    for i in range(len(starts) - 1):
                        # Extract message block (from this message start to next message start)
                        msg_start = starts[i]
                        msg_end = starts[i + 1]
                        msg_text = content[msg_start:msg_end].rstrip()
                        
                        # Parse the message (smaller regex operation, much faster)
                        match = re.match(msg_pattern, msg_text, re.DOTALL)
                        if not match:
                            # Try bracket format
                            match = re.match(bracket_pattern, msg_text, re.DOTALL)
                        
                        if match:
                            message_list.append(match)
                    
                    logger.info(f"Parsed {len(message_list)} messages from boundaries")
                
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
                        # WhatsApp format: DD/MM/YYYY, HH:MM (no seconds)
                        datetime_str = f"{date_str} {time_str}"
                        # Try DD/MM/YYYY first (most common)
                        try:
                            source_timestamp = datetime.strptime(datetime_str, "%d/%m/%Y %H:%M")
                        except ValueError:
                            # Try MM/DD/YYYY (US format)
                            try:
                                source_timestamp = datetime.strptime(datetime_str, "%m/%d/%Y %H:%M")
                            except ValueError:
                                # Try with seconds if time has them
                                if ':' in time_str and time_str.count(':') == 2:
                                    try:
                                        source_timestamp = datetime.strptime(datetime_str, "%d/%m/%Y %H:%M:%S")
                                    except ValueError:
                                        source_timestamp = datetime.strptime(datetime_str, "%m/%d/%Y %H:%M:%S")
                                else:
                                    raise ValueError("Unknown date format")
                    except ValueError as e:
                        logger.warning(f"Could not parse timestamp: {datetime_str}, error: {e}, using current time")
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

