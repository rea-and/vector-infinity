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
        super().__init__("gmail")
        self.service = None
        self._oauth_flow = None  # Store OAuth flow for web-based auth
        self._latest_timestamp = None  # For incremental imports
        # Don't authenticate on init - do it lazily when needed
        # self._authenticate()
    
    def set_latest_timestamp(self, timestamp):
        """Set the latest imported timestamp for incremental imports."""
        self._latest_timestamp = timestamp
    
    def get_authorization_url(self, state):
        """Get OAuth authorization URL for web-based authentication."""
        credentials_path = Path(__file__).parent / "credentials.json"
        if not credentials_path.exists():
            logger.warning("Gmail credentials.json not found")
            return None
        
        try:
            from flask import request
            import config
            
            # Check if BASE_URL is explicitly configured
            if config.BASE_URL:
                base_url = config.BASE_URL.rstrip('/')
                logger.info(f"Using configured BASE_URL: {base_url}")
            else:
                # Get the base URL from the request
                # Use scheme and host from request, but prefer X-Forwarded-Proto if behind proxy (Nginx)
                scheme = request.headers.get('X-Forwarded-Proto', request.scheme)
                host = request.headers.get('X-Forwarded-Host', request.host)
                
                # Remove port from host if present (Google OAuth doesn't use ports in redirect URIs)
                if ':' in host:
                    host = host.split(':')[0]
                
                # Google requires HTTPS for sensitive scopes like Gmail
                # If we're on HTTP, try to detect if we should use HTTPS
                if scheme == 'http':
                    # Check if we're behind a proxy that handles HTTPS (Nginx with SSL)
                    if request.headers.get('X-Forwarded-Proto') == 'https':
                        scheme = 'https'
                    # If we have a domain (not localhost/IP), we likely need HTTPS
                    elif host and not host.startswith('localhost') and not host.startswith('127.0.0.1'):
                        # It's a domain name, likely needs HTTPS
                        logger.info(f"Gmail API requires HTTPS. Detected domain '{host}' but scheme is HTTP. "
                                 "Forcing HTTPS.")
                        scheme = 'https'
                    else:
                        # For Gmail API, we need HTTPS - warn the user
                        logger.warning("Gmail API requires HTTPS. Current scheme is HTTP. "
                                     "Please set up HTTPS with Nginx and Let's Encrypt (see README.md).")
                        # Still use HTTP for now, but it will fail at Google's end
                        # The error message will guide the user
                
                base_url = f"{scheme}://{host}"
                logger.info(f"Auto-detected base URL: {base_url} (from scheme={scheme}, host={host})")
            
            redirect_uri = f"{base_url}/api/plugins/gmail/auth/callback"
            logger.info(f"Using redirect URI: {redirect_uri}")
            
            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_path), SCOPES)
            flow.redirect_uri = redirect_uri
            
            # Store flow in app's oauth_flows dict (accessed via app context)
            from flask import current_app
            if hasattr(current_app, 'oauth_flows'):
                current_app.oauth_flows[state] = {
                    'flow': flow,
                    'plugin_name': 'gmail',
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
            # If we have a latest timestamp, only fetch emails after that (incremental import)
            if self._latest_timestamp:
                # Add 1 second to avoid re-fetching the last email
                after_timestamp = self._latest_timestamp + timedelta(seconds=1)
                after_date = after_timestamp.strftime("%Y/%m/%d")
                query = f"after:{after_date}"
                logger.info(f"Incremental import: fetching emails after {after_date} (latest imported: {self._latest_timestamp.isoformat()})")
            else:
                # Default: get emails from last N days (first import or full import)
                after_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y/%m/%d")
                query = f"after:{after_date}"
        
        logger.info(f"Gmail query: {query}, max_results: {max_results}, days_back: {days_back}")
        
        try:
            # Fetch all messages using pagination
            all_message_ids = []
            page_token = None
            page_count = 0
            max_pages = 1000  # Safety limit to prevent infinite loops
            
            logger.info("Fetching message list from Gmail API (with pagination)...")
            
            while page_count < max_pages:
                # Request up to 500 messages per page (Gmail API max)
                page_max = min(500, max_results - len(all_message_ids)) if max_results > 0 else 500
                
                request_params = {
                    'userId': 'me',
                    'q': query,
                    'maxResults': page_max
                }
                
                if page_token:
                    request_params['pageToken'] = page_token
                
                messages_response = self.service.users().messages().list(**request_params).execute()
                
                messages_list = messages_response.get('messages', [])
                all_message_ids.extend(messages_list)
                
                result_size_estimate = messages_response.get('resultSizeEstimate', 0)
                page_token = messages_response.get('nextPageToken')
                page_count += 1
                
                logger.info(f"Page {page_count}: Fetched {len(messages_list)} messages (total so far: {len(all_message_ids)}, estimate: {result_size_estimate})")
                
                # Stop if no more pages or we've reached max_results
                if not page_token:
                    logger.info("No more pages to fetch")
                    break
                
                if max_results > 0 and len(all_message_ids) >= max_results:
                    logger.info(f"Reached max_results limit ({max_results})")
                    all_message_ids = all_message_ids[:max_results]
                    break
            
            logger.info(f"Total messages to process: {len(all_message_ids)}")
            
            if not all_message_ids:
                logger.warning(f"No messages found with query: {query}")
                return results
            
            # Process messages with error handling for each message
            processed_count = 0
            error_count = 0
            
            for idx, msg in enumerate(all_message_ids):
                try:
                    # Retry logic for fetching message details
                    max_retries = 3
                    msg_detail = None
                    
                    for attempt in range(max_retries):
                        try:
                            msg_detail = self.service.users().messages().get(
                                userId='me',
                                id=msg['id'],
                                format='full'
                            ).execute()
                            break  # Success, exit retry loop
                        except Exception as fetch_error:
                            if attempt < max_retries - 1:
                                wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                                logger.warning(f"Error fetching message {msg['id']} (attempt {attempt + 1}/{max_retries}): {fetch_error}. Retrying in {wait_time}s...")
                                import time
                                time.sleep(wait_time)
                            else:
                                logger.error(f"Failed to fetch message {msg['id']} after {max_retries} attempts: {fetch_error}")
                                raise
                    
                    if not msg_detail:
                        error_count += 1
                        continue
                    
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
                                try:
                                    if part.get('body', {}).get('data'):
                                        body = base64.urlsafe_b64decode(
                                            part['body']['data']
                                        ).decode('utf-8', errors='ignore')
                                        break
                                except Exception as decode_error:
                                    logger.debug(f"Error decoding body part for message {msg['id']}: {decode_error}")
                                    continue
                    elif payload.get('body', {}).get('data'):
                        import base64
                        try:
                            body = base64.urlsafe_b64decode(
                                payload['body']['data']
                            ).decode('utf-8', errors='ignore')
                        except Exception as decode_error:
                            logger.debug(f"Error decoding body for message {msg['id']}: {decode_error}")
                    
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
                    processed_count += 1
                    
                    # Log progress every 50 messages
                    if (idx + 1) % 50 == 0:
                        logger.info(f"Processed {idx + 1}/{len(all_message_ids)} messages...")
                        
                except Exception as msg_error:
                    error_count += 1
                    logger.warning(f"Error processing message {msg.get('id', 'unknown')}: {msg_error}. Skipping...")
                    continue
            
            logger.info(f"Processed {processed_count} emails from Gmail (errors: {error_count})")
        
        except Exception as e:
            logger.error(f"Error fetching Gmail data: {e}", exc_info=True)
            raise Exception(f"Error fetching Gmail data: {str(e)}")
        
        logger.info(f"Fetched {len(results)} emails from Gmail")
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

