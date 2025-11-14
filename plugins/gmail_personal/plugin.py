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
        # Don't authenticate on init - do it lazily when needed
        # self._authenticate()
    
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
                    creds = flow.run_local_server(port=0)
                except Exception as e:
                    logger.warning(f"Error during OAuth flow: {e}")
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

