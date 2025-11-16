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
        self._user_config = None  # Store user-specific config when provided
    
    def set_user_config(self, config_data: Dict[str, Any]):
        """Set user-specific configuration (called before fetch_data)."""
        self._user_config = config_data
        self.github_token = config_data.get("github_token")
        # Update config with file_urls for fetch_data
        if "file_urls" in config_data:
            self.config["file_urls"] = config_data["file_urls"]
    
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
        
        try:
            response = requests.get(api_url, headers=headers, params=params, timeout=30)
        except requests.exceptions.RequestException as e:
            raise Exception(f"Network error fetching file from GitHub: {e}")
        
        if response.status_code == 404:
            # Try to get more details about why it failed
            error_details = ""
            try:
                error_json = response.json()
                if "message" in error_json:
                    error_details = f" - {error_json['message']}"
            except:
                pass
            raise Exception(f"File not found at {url_parts['path']} in {url_parts['owner']}/{url_parts['repo']} (branch: {url_parts['branch']}){error_details}. Please verify the file path and branch name.")
        elif response.status_code == 403:
            error_details = ""
            try:
                error_json = response.json()
                if "message" in error_json:
                    error_details = f" - {error_json['message']}"
            except:
                pass
            raise Exception(f"Access forbidden for {url}. Check your GitHub token permissions and ensure it has access to the repository.{error_details}")
        elif response.status_code == 401:
            raise Exception(f"Authentication failed. Please check your GitHub token is valid and not expired.")
        elif response.status_code != 200:
            error_details = response.text[:500]  # Limit error message length
            raise Exception(f"GitHub API error ({response.status_code}): {error_details}")
        
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
        # Use user-specific config if available, otherwise fall back to plugin config
        if self._user_config:
            file_urls = self._user_config.get("file_urls", [])
            token = self._user_config.get("github_token")
        else:
            file_urls = self.config.get("file_urls", [])
            token = self.github_token
        
        if not token:
            raise Exception("GitHub token not set. Please configure the plugin first.")
        
        if not file_urls:
            logger.warning("No file URLs configured for GitHub Context plugin")
            return []
        
        # Use the token from user config
        original_token = self.github_token
        self.github_token = token
        
        data_items = []
        
        for url in file_urls:
            try:
                logger.info(f"Fetching file from GitHub: {url}")
                # Validate URL format before attempting to fetch
                try:
                    url_parts = self._parse_github_url(url)
                    logger.debug(f"Parsed URL: owner={url_parts['owner']}, repo={url_parts['repo']}, branch={url_parts['branch']}, path={url_parts['path']}")
                except ValueError as parse_error:
                    logger.error(f"Invalid GitHub URL format: {url} - {parse_error}")
                    raise Exception(f"Invalid GitHub URL format: {url}. Expected format: https://github.com/owner/repo/blob/branch/path/to/file.txt")
                
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

