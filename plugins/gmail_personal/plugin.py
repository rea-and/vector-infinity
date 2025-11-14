"""Gmail Personal plugin."""
from plugin_base import DataSourcePlugin
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import os
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']


class Plugin(DataSourcePlugin):
    """Gmail Personal data source plugin."""
    
    def __init__(self):
        super().__init__("gmail_personal")
        self.service = None
        self._oauth_flow = None  # Store OAuth flow for web-based auth
        # Don't authenticate on init - do it lazily when needed
        # self._authenticate()
    
    def get_authorization_url(self, state):
        """Get OAuth authorization URL for web-based authentication."""
        credentials_path = Path(__file__).parent / "credentials.json"
        if not credentials_path.exists():
            logger.warning("Gmail credentials.json not found")
            return None
        
        try:
            from flask import request
            # Get the base URL from the request
            # Use scheme and host from request, but prefer X-Forwarded-Proto if behind proxy
            scheme = request.headers.get('X-Forwarded-Proto', request.scheme)
            host = request.headers.get('X-Forwarded-Host', request.host)
            
            # Google requires HTTPS for sensitive scopes like Gmail
            # If we're on HTTP, try to detect if we should use HTTPS
            if scheme == 'http':
                # Check if we're behind a proxy that handles HTTPS
                if request.headers.get('X-Forwarded-Proto') == 'https':
                    scheme = 'https'
                # If we have a domain (not localhost/IP), we likely need HTTPS
                elif host and not host.startswith('localhost') and not host.startswith('127.0.0.1') and ':' not in host.split('.')[0]:
                    # It's a domain name, likely needs HTTPS
                    logger.warning(f"Gmail API requires HTTPS. Detected domain '{host}' but scheme is HTTP. "
                                 "Forcing HTTPS. Make sure your domain has HTTPS set up or you're using ngrok.")
                    scheme = 'https'
                else:
                    # For Gmail API, we need HTTPS - warn the user
                    logger.warning("Gmail API requires HTTPS. Current scheme is HTTP. "
                                 "Please set up HTTPS or use a reverse proxy with SSL termination.")
                    # Still use HTTP for now, but it will fail at Google's end
                    # The error message will guide the user
            
            base_url = f"{scheme}://{host}"
            redirect_uri = f"{base_url}/api/plugins/gmail_personal/auth/callback"
            
            logger.info(f"Using redirect URI: {redirect_uri}")
            
            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_path), SCOPES)
            flow.redirect_uri = redirect_uri
            
            # Store flow in app's oauth_flows dict (accessed via app context)
            from flask import current_app
            if hasattr(current_app, 'oauth_flows'):
                current_app.oauth_flows[state] = {
                    'flow': flow,
                    'plugin_name': 'gmail_personal',
                    'redirect_uri': redirect_uri  # Store for debugging
                }
            else:
                # Fallback: store in instance (less ideal but works)
                self._oauth_flow = flow
                self._oauth_state = state
            
            auth_url, _ = flow.authorization_url(
                access_type='offline',
                include_granted_scopes='true',
                state=state,
                prompt='consent'
            )
            return auth_url
        except Exception as e:
            logger.error(f"Error generating authorization URL: {e}", exc_info=True)
            return None
    
    def complete_authorization(self, code, state):
        """Complete OAuth flow with authorization code."""
        flow = None
        
        # Try to get flow from app's oauth_flows dict
        try:
            from flask import current_app
            if hasattr(current_app, 'oauth_flows') and state in current_app.oauth_flows:
                flow = current_app.oauth_flows[state]['flow']
        except:
            pass
        
        # Fallback to instance flow
        if not flow and self._oauth_flow and self._oauth_state == state:
            flow = self._oauth_flow
        
        if not flow:
            logger.error("OAuth flow not found for state")
            return False
        
        try:
            token_path = Path(__file__).parent / "token.json"
            
            # Exchange code for token
            flow.fetch_token(code=code)
            creds = flow.credentials
            
            # Save token
            with open(token_path, 'w') as token:
                token.write(creds.to_json())
            
            # Build service
            self.service = build('gmail', 'v1', credentials=creds)
            
            # Clear flow
            self._oauth_flow = None
            self._oauth_state = None
            
            logger.info("Gmail authentication completed successfully")
            return True
        except Exception as e:
            logger.error(f"Error completing authorization: {e}", exc_info=True)
            self._oauth_flow = None
            self._oauth_state = None
            return False
    
    def _authenticate(self):
        """Authenticate with Gmail API."""
        if self.service:
            return  # Already authenticated
        
        creds = None
        token_path = Path(__file__).parent / "token.json"
        credentials_path = Path(__file__).parent / "credentials.json"
        
        if token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
            except Exception as e:
                logger.warning(f"Error loading token: {e}")
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    logger.warning(f"Error refreshing token: {e}")
                    creds = None
            else:
                if not credentials_path.exists():
                    logger.warning("Gmail credentials.json not found")
                    return  # Can't authenticate without credentials
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(credentials_path), SCOPES)
                    # Use local server - it will provide a URL you can open in browser
                    # Try to open browser automatically, but if it fails, just provide the URL
                    try:
                        creds = flow.run_local_server(port=0, open_browser=True)
                    except Exception as browser_error:
                        # Browser couldn't be opened automatically, but local server still works
                        logger.info("Could not open browser automatically, but local server is running.")
                        logger.info("The authorization URL will be displayed - you can open it manually in your browser.")
                        # Try again without auto-opening browser
                        creds = flow.run_local_server(port=0, open_browser=False)
                except Exception as e:
                    logger.warning(f"Error during OAuth flow: {e}")
                    logger.info("If automatic browser opening failed, you can manually authenticate:")
                    logger.info("1. Look for the authorization URL in the logs above")
                    logger.info("2. Open that URL in your browser")
                    logger.info("3. Complete the authorization")
                    logger.info("4. The local server will automatically receive the authorization code")
                    return
            
            if creds:
                try:
                    with open(token_path, 'w') as token:
                        token.write(creds.to_json())
                except Exception as e:
                    logger.warning(f"Error saving token: {e}")
        
        if creds:
            try:
                self.service = build('gmail', 'v1', credentials=creds)
            except Exception as e:
                logger.warning(f"Error building Gmail service: {e}")
    
    def fetch_data(self):
        """Fetch emails from Gmail."""
        # Authenticate if not already done
        if not self.service:
            self._authenticate()
        
        if not self.service:
            raise Exception("Gmail service not authenticated. Please set up credentials.json")
        
        results = []
        days_back = self.config.get("days_back", 7)
        max_results = self.config.get("max_results", 100)
        
        query = self.config.get("query", "")
        if not query:
            # Default: get emails from last N days
            after_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y/%m/%d")
            query = f"after:{after_date}"
        
        try:
            messages = self.service.users().messages().list(
                userId='me',
                q=query,
                maxResults=max_results
            ).execute()
            
            for msg in messages.get('messages', [])[:max_results]:
                msg_detail = self.service.users().messages().get(
                    userId='me',
                    id=msg['id'],
                    format='full'
                ).execute()
                
                headers = {h['name']: h['value'] for h in msg_detail['payload'].get('headers', [])}
                subject = headers.get('Subject', 'No Subject')
                from_addr = headers.get('From', 'Unknown')
                date_str = headers.get('Date', '')
                
                # Extract body
                body = ""
                payload = msg_detail['payload']
                if 'parts' in payload:
                    for part in payload['parts']:
                        if part['mimeType'] == 'text/plain':
                            import base64
                            body = base64.urlsafe_b64decode(
                                part['body']['data']
                            ).decode('utf-8', errors='ignore')
                            break
                elif payload.get('body', {}).get('data'):
                    import base64
                    body = base64.urlsafe_b64decode(
                        payload['body']['data']
                    ).decode('utf-8', errors='ignore')
                
                # Parse date
                source_timestamp = None
                try:
                    from email.utils import parsedate_to_datetime
                    source_timestamp = parsedate_to_datetime(date_str)
                except:
                    pass
                
                results.append({
                    "source_id": msg['id'],
                    "item_type": "email",
                    "title": subject,
                    "content": f"From: {from_addr}\n\n{body[:2000]}",  # Limit content
                    "metadata": {
                        "from": from_addr,
                        "to": headers.get('To', ''),
                        "date": date_str,
                        "thread_id": msg_detail.get('threadId', '')
                    },
                    "source_timestamp": source_timestamp
                })
        
        except Exception as e:
            raise Exception(f"Error fetching Gmail data: {str(e)}")
        
        return results
    
    def test_connection(self):
        """Test Gmail connection."""
        try:
            if not self.service:
                return False
            self.service.users().getProfile(userId='me').execute()
            return True
        except:
            return False
    
    def get_config_schema(self):
        """Get configuration schema."""
        schema = super().get_config_schema()
        schema.update({
            "days_back": {
                "type": "number",
                "default": 7,
                "description": "Number of days to look back for emails"
            },
            "max_results": {
                "type": "number",
                "default": 100,
                "description": "Maximum number of emails to fetch"
            },
            "query": {
                "type": "string",
                "default": "",
                "description": "Gmail search query (optional, defaults to date-based)"
            }
        })
        return schema

