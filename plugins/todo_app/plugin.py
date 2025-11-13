"""Generic TODO app plugin (works with any REST API)."""
from plugin_base import DataSourcePlugin
import requests
from datetime import datetime
from typing import List, Dict, Any


class Plugin(DataSourcePlugin):
    """Generic TODO app data source plugin."""
    
    def __init__(self):
        super().__init__("todo_app")
    
    def fetch_data(self):
        """Fetch todos from API."""
        api_url = self.config.get("api_url")
        api_key = self.config.get("api_key", "")
        headers = {}
        
        if not api_url:
            raise Exception("api_url not configured")
        
        if api_key:
            auth_type = self.config.get("auth_type", "bearer")  # bearer, header, basic
            if auth_type == "bearer":
                headers["Authorization"] = f"Bearer {api_key}"
            elif auth_type == "header":
                header_name = self.config.get("api_key_header", "X-API-Key")
                headers[header_name] = api_key
            elif auth_type == "basic":
                # For basic auth, api_key should be "username:password"
                from requests.auth import HTTPBasicAuth
                username, password = api_key.split(":", 1)
                auth = HTTPBasicAuth(username, password)
            else:
                auth = None
        else:
            auth = None
        
        try:
            response = requests.get(
                api_url,
                headers=headers,
                auth=auth if 'auth' in locals() else None,
                timeout=30
            )
            response.raise_for_status()
            
            data = response.json()
            
            # Handle different response formats
            items = data
            if isinstance(data, dict):
                # Try common keys
                items = data.get("items", data.get("todos", data.get("data", [data])))
            
            if not isinstance(items, list):
                items = [items]
            
            results = []
            for item in items:
                # Extract common fields
                source_id = str(item.get("id", item.get("_id", item.get("uuid", ""))))
                title = item.get("title", item.get("name", item.get("text", "Untitled")))
                content = item.get("description", item.get("content", item.get("notes", "")))
                
                # Parse timestamp
                source_timestamp = None
                for date_field in ["created_at", "created", "date", "timestamp", "due_date"]:
                    if date_field in item and item[date_field]:
                        try:
                            if isinstance(item[date_field], str):
                                source_timestamp = datetime.fromisoformat(item[date_field].replace('Z', '+00:00'))
                            elif isinstance(item[date_field], (int, float)):
                                source_timestamp = datetime.fromtimestamp(item[date_field])
                            break
                        except:
                            pass
                
                results.append({
                    "source_id": source_id,
                    "item_type": "todo",
                    "title": title,
                    "content": content,
                    "metadata": item,
                    "source_timestamp": source_timestamp
                })
            
            return results
        
        except Exception as e:
            raise Exception(f"Error fetching TODO data: {str(e)}")
    
    def test_connection(self):
        """Test TODO API connection."""
        try:
            api_url = self.config.get("api_url")
            if not api_url:
                return False
            
            api_key = self.config.get("api_key", "")
            headers = {}
            
            if api_key:
                auth_type = self.config.get("auth_type", "bearer")
                if auth_type == "bearer":
                    headers["Authorization"] = f"Bearer {api_key}"
                elif auth_type == "header":
                    header_name = self.config.get("api_key_header", "X-API-Key")
                    headers[header_name] = api_key
            
            response = requests.get(api_url, headers=headers, timeout=10)
            return response.status_code == 200
        except:
            return False
    
    def get_config_schema(self):
        """Get configuration schema."""
        schema = super().get_config_schema()
        schema.update({
            "api_url": {
                "type": "string",
                "default": "",
                "description": "API endpoint URL"
            },
            "api_key": {
                "type": "string",
                "default": "",
                "description": "API key or token"
            },
            "auth_type": {
                "type": "string",
                "default": "bearer",
                "description": "Authentication type: bearer, header, or basic"
            },
            "api_key_header": {
                "type": "string",
                "default": "X-API-Key",
                "description": "Header name for API key (if auth_type is header)"
            }
        })
        return schema

