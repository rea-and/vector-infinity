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
        
        results = []
        
        try:
            # Extract zip file
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                
                with zipfile.ZipFile(self._uploaded_file_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_path)
                
                # Find the txt file (WhatsApp exports are usually named like "WhatsApp Chat with Angel.txt")
                txt_files = list(temp_path.glob("*.txt"))
                if not txt_files:
                    raise Exception("No .txt file found in the zip archive")
                
                chat_file = txt_files[0]
                logger.info(f"Found chat file: {chat_file.name}")
                
                # Parse WhatsApp chat format
                # Format: [DD/MM/YYYY, HH:MM:SS] Sender: Message
                # Example: [14/11/2024, 10:30:45] Andrea: Hello!
                
                with open(chat_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # Split into messages
                # Pattern: [date, time] sender: message
                pattern = r'\[(\d{1,2}/\d{1,2}/\d{4}),\s*(\d{1,2}:\d{2}:\d{2})\]\s*([^:]+):\s*(.*?)(?=\[\d{1,2}/\d{1,2}/\d{4}|\Z)'
                
                messages = re.finditer(pattern, content, re.DOTALL | re.MULTILINE)
                
                message_count = 0
                for match in messages:
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
                
                logger.info(f"Parsed {message_count} messages from WhatsApp chat")
                
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

