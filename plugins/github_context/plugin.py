"""GitHub Context plugin - import text files from GitHub repositories."""
from plugin_base import DataSourcePlugin
from pathlib import Path
import json
import logging
import requests
from typing import List, Dict, Any
from datetime import datetime, timezone
import re

logger = logging.getLogger(__name__)

# GitHub API base URL
GITHUB_API_BASE = "https://api.github.com"


class Plugin(DataSourcePlugin):
    """GitHub Context data source plugin."""
    
    def __init__(self):
        super().__init__("github_context")
        self.github_token = None
        self._load_token()
    
    def _load_token(self):
        """Load GitHub token from token.json file."""
        token_path = Path(__file__).parent / "token.json"
        if token_path.exists():
            try:
                with open(token_path, 'r') as f:
                    token_data = json.load(f)
                    self.github_token = token_data.get("github_token")
            except Exception as e:
                logger.error(f"Error loading GitHub token: {e}")
    
    def save_token(self, token: str):
        """Save GitHub token to token.json file."""
        token_path = Path(__file__).parent / "token.json"
        token_data = {
            "github_token": token
        }
        with open(token_path, 'w') as f:
            json.dump(token_data, f, indent=2)
        self.github_token = token
        logger.info("GitHub token saved successfully")
    
    def _parse_github_url(self, url: str) -> Dict[str, str]:
        """
        Parse a GitHub URL to extract owner, repo, and file path.
        
        Supports formats:
        - https://github.com/owner/repo/blob/branch/path/to/file.txt
        - https://github.com/owner/repo/blob/main/path/to/file.txt
        
        Returns:
            Dict with 'owner', 'repo', 'branch', 'path' keys
        """
        # Pattern: https://github.com/{owner}/{repo}/blob/{branch}/{path}
        pattern = r'https://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)'
        match = re.match(pattern, url)
        
        if not match:
            raise ValueError(f"Invalid GitHub URL format: {url}")
        
        return {
            'owner': match.group(1),
            'repo': match.group(2),
            'branch': match.group(3),
            'path': match.group(4)
        }
    
    def _fetch_file_from_github(self, url: str) -> Dict[str, Any]:
        """
        Fetch a file from GitHub using the API.
        
        Args:
            url: GitHub file URL (e.g., https://github.com/owner/repo/blob/branch/path/file.txt)
        
        Returns:
            Dict with file content and metadata
        """
        if not self.github_token:
            raise Exception("GitHub token not set. Please configure the plugin first.")
        
        # Parse URL
        url_parts = self._parse_github_url(url)
        
        # GitHub API endpoint: GET /repos/{owner}/{repo}/contents/{path}
        api_url = f"{GITHUB_API_BASE}/repos/{url_parts['owner']}/{url_parts['repo']}/contents/{url_parts['path']}"
        
        headers = {
            "Accept": "application/vnd.github.v3.raw",
            "Authorization": f"token {self.github_token}",
            "User-Agent": "Vector-Infinity"
        }
        
        # Add ref parameter to specify branch
        params = {"ref": url_parts['branch']}
        
        logger.info(f"Fetching file from GitHub: {api_url} (branch: {url_parts['branch']})")
        
        response = requests.get(api_url, headers=headers, params=params)
        
        if response.status_code == 404:
            raise Exception(f"File not found: {url}")
        elif response.status_code == 403:
            raise Exception(f"Access forbidden. Check your GitHub token permissions: {url}")
        elif response.status_code != 200:
            raise Exception(f"GitHub API error ({response.status_code}): {response.text}")
        
        # Get file content (raw)
        content = response.text
        
        # Also get file metadata
        metadata_url = f"{GITHUB_API_BASE}/repos/{url_parts['owner']}/{url_parts['repo']}/contents/{url_parts['path']}"
        metadata_headers = {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"token {self.github_token}",
            "User-Agent": "Vector-Infinity"
        }
        metadata_response = requests.get(metadata_url, headers=metadata_headers, params=params)
        
        metadata = {}
        if metadata_response.status_code == 200:
            file_info = metadata_response.json()
            metadata = {
                "sha": file_info.get("sha"),
                "size": file_info.get("size"),
                "html_url": file_info.get("html_url"),
                "download_url": file_info.get("download_url")
            }
        
        return {
            "content": content,
            "url": url,
            "owner": url_parts['owner'],
            "repo": url_parts['repo'],
            "branch": url_parts['branch'],
            "path": url_parts['path'],
            "filename": Path(url_parts['path']).name,
            "metadata": metadata
        }
    
    def fetch_data(self) -> List[Dict[str, Any]]:
        """Fetch data from GitHub files."""
        if not self.github_token:
            raise Exception("GitHub token not set. Please configure the plugin first.")
        
        file_urls = self.config.get("file_urls", [])
        if not file_urls:
            logger.warning("No file URLs configured for GitHub Context plugin")
            return []
        
        data_items = []
        
        for url in file_urls:
            try:
                logger.info(f"Fetching file from GitHub: {url}")
                file_data = self._fetch_file_from_github(url)
                
                # Create a data item
                data_item = {
                    "source_id": f"github_{file_data['owner']}_{file_data['repo']}_{file_data['path'].replace('/', '_')}",
                    "item_type": "github_file",
                    "title": f"{file_data['filename']} ({file_data['repo']})",
                    "content": f"Source: GitHub - {file_data['owner']}/{file_data['repo']}\n"
                              f"File: {file_data['path']}\n"
                              f"Branch: {file_data['branch']}\n"
                              f"URL: {file_data['url']}\n\n"
                              f"Content:\n{file_data['content']}",
                    "metadata": {
                        "github_url": file_data['url'],
                        "owner": file_data['owner'],
                        "repo": file_data['repo'],
                        "branch": file_data['branch'],
                        "path": file_data['path'],
                        "filename": file_data['filename'],
                        **file_data['metadata']
                    },
                    "source_timestamp": datetime.now(timezone.utc)  # Use current time as we don't have file modification time easily
                }
                
                data_items.append(data_item)
                logger.info(f"Successfully fetched file: {file_data['filename']}")
                
            except Exception as e:
                logger.error(f"Error fetching file {url}: {e}", exc_info=True)
                # Continue with other files even if one fails
                continue
        
        logger.info(f"Fetched {len(data_items)} files from GitHub")
        return data_items
    
    def test_connection(self) -> bool:
        """Test GitHub connection."""
        try:
            if not self.github_token:
                return False
            
            # Test by making a simple API call to get authenticated user
            headers = {
                "Authorization": f"token {self.github_token}",
                "User-Agent": "Vector-Infinity"
            }
            response = requests.get(f"{GITHUB_API_BASE}/user", headers=headers)
            
            if response.status_code == 200:
                user_data = response.json()
                logger.info(f"GitHub connection test successful. Authenticated as: {user_data.get('login')}")
                return True
            elif response.status_code == 401:
                logger.error("GitHub token is invalid or expired")
                return False
            else:
                logger.error(f"GitHub API error: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logger.error(f"GitHub connection test failed: {e}")
            return False
    
    def get_config_schema(self) -> Dict[str, Any]:
        """Return configuration schema."""
        schema = super().get_config_schema()
        schema["file_urls"] = {
            "type": "array",
            "default": [],
            "description": "List of GitHub file URLs to import (e.g., https://github.com/owner/repo/blob/branch/path/file.txt)"
        }
        return schema

