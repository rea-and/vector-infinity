"""Google Calendar plugin."""
from plugin_base import DataSourcePlugin
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from datetime import datetime, timedelta
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']


class Plugin(DataSourcePlugin):
    """Google Calendar data source plugin."""
    
    def __init__(self):
        super().__init__("calendar")
        self.service = None
        # Don't authenticate on init - do it lazily when needed
    
    def _authenticate(self):
        """Authenticate with Google Calendar API."""
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
                    logger.warning("Calendar credentials.json not found")
                    return
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
                self.service = build('calendar', 'v3', credentials=creds)
            except Exception as e:
                logger.warning(f"Error building Calendar service: {e}")
    
    def fetch_data(self):
        """Fetch calendar events."""
        # Authenticate if not already done
        if not self.service:
            self._authenticate()
        
        if not self.service:
            raise Exception("Calendar service not authenticated. Please set up credentials.json")
        
        results = []
        days_back = self.config.get("days_back", 7)
        days_forward = self.config.get("days_forward", 7)
        max_results = self.config.get("max_results", 250)
        
        time_min = (datetime.now() - timedelta(days=days_back)).isoformat() + 'Z'
        time_max = (datetime.now() + timedelta(days=days_forward)).isoformat() + 'Z'
        
        try:
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                end = event['end'].get('dateTime', event['end'].get('date'))
                summary = event.get('summary', 'No Title')
                description = event.get('description', '')
                location = event.get('location', '')
                
                # Parse start time
                source_timestamp = None
                try:
                    if 'T' in start:
                        source_timestamp = datetime.fromisoformat(start.replace('Z', '+00:00'))
                    else:
                        source_timestamp = datetime.fromisoformat(start)
                except:
                    pass
                
                content = f"Start: {start}\nEnd: {end}"
                if location:
                    content += f"\nLocation: {location}"
                if description:
                    content += f"\n\n{description[:1000]}"
                
                results.append({
                    "source_id": event['id'],
                    "item_type": "calendar_event",
                    "title": summary,
                    "content": content,
                    "metadata": {
                        "start": start,
                        "end": end,
                        "location": location,
                        "status": event.get('status', ''),
                        "html_link": event.get('htmlLink', '')
                    },
                    "source_timestamp": source_timestamp
                })
        
        except Exception as e:
            raise Exception(f"Error fetching Calendar data: {str(e)}")
        
        return results
    
    def test_connection(self):
        """Test Calendar connection."""
        try:
            if not self.service:
                return False
            self.service.calendarList().list().execute()
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
                "description": "Number of days to look back"
            },
            "days_forward": {
                "type": "number",
                "default": 7,
                "description": "Number of days to look forward"
            },
            "max_results": {
                "type": "number",
                "default": 250,
                "description": "Maximum number of events to fetch"
            }
        })
        return schema

