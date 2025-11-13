"""Base class for data source plugins."""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from datetime import datetime
import json
from pathlib import Path
import config


class DataSourcePlugin(ABC):
    """Base class for all data source plugins."""
    
    def __init__(self, plugin_name: str):
        self.plugin_name = plugin_name
        self.config_path = config.PLUGINS_DIR / plugin_name / "config.json"
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load plugin configuration from config.json."""
        if self.config_path.exists():
            with open(self.config_path, 'r') as f:
                return json.load(f)
        return {}
    
    def save_config(self, config_data: Dict[str, Any]):
        """Save plugin configuration to config.json."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w') as f:
            json.dump(config_data, f, indent=2)
        self.config = config_data
    
    @abstractmethod
    def fetch_data(self) -> List[Dict[str, Any]]:
        """
        Fetch data from the source.
        
        Returns:
            List of dictionaries, each containing:
            - source_id: unique identifier from source
            - item_type: type of item (email, todo, etc.)
            - title: title/subject
            - content: main content
            - metadata: additional structured data
            - source_timestamp: original timestamp from source
        """
        pass
    
    @abstractmethod
    def test_connection(self) -> bool:
        """Test if the plugin can connect to the data source."""
        pass
    
    def get_config_schema(self) -> Dict[str, Any]:
        """
        Return the configuration schema for this plugin.
        Used by the UI to render configuration forms.
        """
        return {
            "enabled": {"type": "boolean", "default": False, "description": "Enable this plugin"},
        }

