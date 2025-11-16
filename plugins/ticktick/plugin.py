"""TickTick plugin - import tasks from TickTick account."""
from plugin_base import DataSourcePlugin
from pathlib import Path
import json
import logging
import requests
from typing import List, Dict, Any
from datetime import datetime, timezone
import secrets
import base64

logger = logging.getLogger(__name__)

# TickTick API endpoints
TICKTICK_API_BASE = "https://api.ticktick.com/api/v2"
TICKTICK_AUTH_URL = "https://ticktick.com/oauth/authorize"
TICKTICK_TOKEN_URL = "https://ticktick.com/oauth/token"


class Plugin(DataSourcePlugin):
    """TickTick data source plugin."""
    
    def __init__(self):
        super().__init__("ticktick")
        self.access_token = None
        self.refresh_token = None
        self.client_id = None
        self.client_secret = None
    
    def _load_tokens(self):
        """Load OAuth tokens from token.json file."""
        token_path = Path(__file__).parent / "token.json"
        if token_path.exists():
            try:
                with open(token_path, 'r') as f:
                    token_data = json.load(f)
                    self.access_token = token_data.get("access_token")
                    self.refresh_token = token_data.get("refresh_token")
                    self.client_id = token_data.get("client_id")
                    self.client_secret = token_data.get("client_secret")
                    return True
            except Exception as e:
                logger.error(f"Error loading TickTick tokens: {e}")
        return False
    
    def _save_tokens(self):
        """Save OAuth tokens to token.json file."""
        token_path = Path(__file__).parent / "token.json"
        try:
            with open(token_path, 'w') as f:
                json.dump({
                    "access_token": self.access_token,
                    "refresh_token": self.refresh_token,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret
                }, f)
        except Exception as e:
            logger.error(f"Error saving TickTick tokens: {e}")
    
    def _refresh_access_token(self):
        """Refresh the access token using refresh token."""
        if not self.refresh_token or not self.client_id or not self.client_secret:
            return False
        
        try:
            # TickTick uses Basic Auth with client_id:client_secret
            auth_string = f"{self.client_id}:{self.client_secret}"
            auth_bytes = auth_string.encode('ascii')
            auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
            
            response = requests.post(
                TICKTICK_TOKEN_URL,
                headers={
                    "Authorization": f"Basic {auth_b64}",
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token
                },
                timeout=30
            )
            
            if response.status_code == 200:
                token_data = response.json()
                self.access_token = token_data.get("access_token")
                if "refresh_token" in token_data:
                    self.refresh_token = token_data.get("refresh_token")
                self._save_tokens()
                return True
            else:
                logger.error(f"Error refreshing token: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error refreshing access token: {e}")
            return False
    
    def _get_authenticated_headers(self):
        """Get headers with authentication token."""
        if not self.access_token:
            if not self._load_tokens():
                raise Exception("Not authenticated. Please authenticate first.")
        
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
    
    def _make_authenticated_request(self, method, endpoint, **kwargs):
        """Make an authenticated API request, refreshing token if needed."""
        headers = self._get_authenticated_headers()
        url = f"{TICKTICK_API_BASE}/{endpoint}"
        
        response = requests.request(method, url, headers=headers, **kwargs)
        
        # If unauthorized, try refreshing token once
        if response.status_code == 401:
            logger.info("Access token expired, refreshing...")
            if self._refresh_access_token():
                headers = self._get_authenticated_headers()
                response = requests.request(method, url, headers=headers, **kwargs)
            else:
                raise Exception("Authentication failed. Please re-authenticate.")
        
        return response
    
    def get_authorization_url(self, state):
        """Get OAuth authorization URL for web-based authentication."""
        # Load client credentials from config
        config_path = Path(__file__).parent / "config.json"
        if not config_path.exists():
            logger.error("TickTick config.json not found")
            return None
        
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                self.client_id = config.get("client_id")
                self.client_secret = config.get("client_secret")
            
            if not self.client_id or not self.client_secret:
                logger.error("TickTick client_id or client_secret not configured")
                return None
            
            from flask import request
            
            # Get the base URL from the request
            scheme = request.headers.get('X-Forwarded-Proto', request.scheme)
            host = request.headers.get('X-Forwarded-Host', request.host)
            
            if scheme == 'http':
                if request.headers.get('X-Forwarded-Proto') == 'https':
                    scheme = 'https'
                elif host and not host.startswith('localhost') and not host.startswith('127.0.0.1'):
                    scheme = 'https'
            
            base_url = f"{scheme}://{host}"
            redirect_uri = f"{base_url}/api/plugins/ticktick/auth/callback"
            
            # Store client credentials for later use
            from flask import current_app
            if hasattr(current_app, 'oauth_flows'):
                current_app.oauth_flows[state] = {
                    'plugin_name': 'ticktick',
                    'client_id': self.client_id,
                    'client_secret': self.client_secret,
                    'redirect_uri': redirect_uri
                }
            
            # Build authorization URL
            auth_url = (
                f"{TICKTICK_AUTH_URL}?"
                f"client_id={self.client_id}&"
                f"redirect_uri={redirect_uri}&"
                f"response_type=code&"
                f"scope=read:task&"
                f"state={state}"
            )
            
            return auth_url
        except Exception as e:
            logger.error(f"Error generating authorization URL: {e}", exc_info=True)
            return None
    
    def complete_authorization(self, code, state):
        """Complete OAuth flow with authorization code."""
        try:
            from flask import current_app
            
            # Get stored OAuth flow data
            flow_data = None
            if hasattr(current_app, 'oauth_flows') and state in current_app.oauth_flows:
                flow_data = current_app.oauth_flows[state]
                self.client_id = flow_data.get('client_id')
                self.client_secret = flow_data.get('client_secret')
                redirect_uri = flow_data.get('redirect_uri')
            else:
                # Fallback: load from config
                config_path = Path(__file__).parent / "config.json"
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    self.client_id = config.get("client_id")
                    self.client_secret = config.get("client_secret")
                
                from flask import request
                scheme = request.headers.get('X-Forwarded-Proto', request.scheme)
                host = request.headers.get('X-Forwarded-Host', request.host)
                if scheme == 'http' and (request.headers.get('X-Forwarded-Proto') == 'https' or 
                                        (host and not host.startswith('localhost') and not host.startswith('127.0.0.1'))):
                    scheme = 'https'
                redirect_uri = f"{scheme}://{host}/api/plugins/ticktick/auth/callback"
            
            # Exchange authorization code for tokens
            auth_string = f"{self.client_id}:{self.client_secret}"
            auth_bytes = auth_string.encode('ascii')
            auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
            
            response = requests.post(
                TICKTICK_TOKEN_URL,
                headers={
                    "Authorization": f"Basic {auth_b64}",
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri
                },
                timeout=30
            )
            
            if response.status_code == 200:
                token_data = response.json()
                self.access_token = token_data.get("access_token")
                self.refresh_token = token_data.get("refresh_token")
                self._save_tokens()
                logger.info("TickTick authentication successful")
                return True
            else:
                logger.error(f"Error completing authorization: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error completing TickTick authorization: {e}", exc_info=True)
            return False
    
    def fetch_data(self) -> List[Dict[str, Any]]:
        """Fetch tasks from TickTick (both completed and open)."""
        if not self._load_tokens():
            raise Exception("Not authenticated. Please authenticate first.")
        
        data_items = []
        
        try:
            # Fetch all tasks (both completed and open)
            # TickTick API endpoint for getting tasks - use batch query endpoint
            # First, get all projects to understand the structure
            projects_response = self._make_authenticated_request("GET", "project")
            if projects_response.status_code != 200:
                logger.warning(f"Could not fetch projects: {projects_response.status_code}")
            
            # Fetch tasks using batch query
            # TickTick uses a batch query endpoint that requires a query object
            query_data = {
                "queries": [
                    {
                        "query": "",
                        "projectIds": [],
                        "status": [0, 2]  # 0 = open, 2 = completed
                    }
                ]
            }
            
            response = self._make_authenticated_request("POST", "batch/check/0", json=query_data)
            
            if response.status_code != 200:
                # Fallback: try simpler endpoint
                response = self._make_authenticated_request("GET", "task")
                if response.status_code != 200:
                    raise Exception(f"TickTick API error: {response.status_code} - {response.text}")
            
            result = response.json()
            # The response structure may vary - handle both array and object responses
            if isinstance(result, dict):
                tasks = result.get("tasks", []) or result.get("data", []) or []
            else:
                tasks = result if isinstance(result, list) else []
            
            # Process each task
            for task in tasks:
                task_id = task.get("id")
                title = task.get("title", "Untitled Task")
                content = task.get("content", "")
                status = task.get("status", 0)  # 0 = open, 2 = completed
                is_completed = status == 2
                project_id = task.get("projectId", "")
                project_name = task.get("projectName", "")
                due_date = task.get("dueDate")
                start_date = task.get("startDate")
                created_time = task.get("createdTime")
                modified_time = task.get("modifiedTime")
                priority = task.get("priority", 0)  # 0 = none, 1 = low, 3 = medium, 5 = high
                tags = task.get("tags", [])
                
                # Format task data
                formatted_content = f"Task: {title}\n"
                formatted_content += f"Status: {'Completed' if is_completed else 'Open'}\n"
                
                if project_name:
                    formatted_content += f"Project: {project_name}\n"
                
                if content:
                    formatted_content += f"Description: {content}\n"
                
                if due_date:
                    due_dt = datetime.fromtimestamp(int(due_date) / 1000, tz=timezone.utc)
                    formatted_content += f"Due Date: {due_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                
                if start_date:
                    start_dt = datetime.fromtimestamp(int(start_date) / 1000, tz=timezone.utc)
                    formatted_content += f"Start Date: {start_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                
                if priority > 0:
                    priority_map = {1: "Low", 3: "Medium", 5: "High"}
                    formatted_content += f"Priority: {priority_map.get(priority, 'Unknown')}\n"
                
                if tags:
                    formatted_content += f"Tags: {', '.join(tags)}\n"
                
                # Determine source timestamp (use modified time if available, otherwise created time)
                source_timestamp = None
                if modified_time:
                    source_timestamp = datetime.fromtimestamp(int(modified_time) / 1000, tz=timezone.utc)
                elif created_time:
                    source_timestamp = datetime.fromtimestamp(int(created_time) / 1000, tz=timezone.utc)
                else:
                    source_timestamp = datetime.now(timezone.utc)
                
                data_item = {
                    "source_id": f"ticktick_task_{task_id}",
                    "item_type": "ticktick_task",
                    "title": f"{title} ({'Completed' if is_completed else 'Open'})",
                    "content": formatted_content,
                    "metadata": {
                        "task_id": task_id,
                        "status": "completed" if is_completed else "open",
                        "project_id": project_id,
                        "project_name": project_name,
                        "priority": priority,
                        "tags": tags,
                        "due_date": due_date,
                        "start_date": start_date,
                        "created_time": created_time,
                        "modified_time": modified_time
                    },
                    "source_timestamp": source_timestamp
                }
                
                data_items.append(data_item)
            
            logger.info(f"Fetched {len(data_items)} tasks from TickTick ({sum(1 for item in data_items if item['metadata']['status'] == 'completed')} completed, {sum(1 for item in data_items if item['metadata']['status'] == 'open')} open)")
            return data_items
            
        except Exception as e:
            logger.error(f"Error fetching TickTick tasks: {e}", exc_info=True)
            raise
    
    def test_connection(self) -> bool:
        """Test TickTick connection."""
        try:
            if not self._load_tokens():
                return False
            
            # Try to fetch user profile to test connection
            response = self._make_authenticated_request("GET", "user")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"TickTick connection test failed: {e}")
            return False
    
    def get_config_schema(self) -> Dict[str, Any]:
        """Return configuration schema."""
        schema = super().get_config_schema()
        schema["client_id"] = {
            "type": "string",
            "default": "",
            "description": "TickTick OAuth Client ID (from TickTick Developer Portal)"
        }
        schema["client_secret"] = {
            "type": "string",
            "default": "",
            "description": "TickTick OAuth Client Secret (from TickTick Developer Portal)"
        }
        return schema

