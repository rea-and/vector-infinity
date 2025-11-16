"""WHOOP health data plugin."""
from plugin_base import DataSourcePlugin
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import logging
import requests
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# WHOOP API endpoints
WHOOP_API_BASE = "https://api.prod.whoop.com"
WHOOP_AUTH_URL = "https://api.prod.whoop.com/oauth/token"
WHOOP_AUTHORIZE_URL = "https://api.prod.whoop.com/oauth/authorize"


class Plugin(DataSourcePlugin):
    """WHOOP health data source plugin."""
    
    def __init__(self):
        super().__init__("whoop")
        self.access_token = None
        self.refresh_token = None
        self.token_expires_at = None
        self._load_tokens()
    
    def _load_tokens(self):
        """Load OAuth tokens from token.json file."""
        token_path = Path(__file__).parent / "token.json"
        if token_path.exists():
            try:
                with open(token_path, 'r') as f:
                    token_data = json.load(f)
                    self.access_token = token_data.get("access_token")
                    self.refresh_token = token_data.get("refresh_token")
                    if token_data.get("expires_at"):
                        self.token_expires_at = datetime.fromisoformat(token_data["expires_at"])
            except Exception as e:
                logger.error(f"Error loading tokens: {e}")
    
    def _save_tokens(self, access_token: str, refresh_token: str, expires_in: int):
        """Save OAuth tokens to token.json file."""
        token_path = Path(__file__).parent / "token.json"
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        token_data = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at.isoformat()
        }
        with open(token_path, 'w') as f:
            json.dump(token_data, f, indent=2)
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_expires_at = expires_at
        logger.info("WHOOP tokens saved successfully")
    
    def _ensure_authenticated(self):
        """Ensure we have a valid access token, refresh if needed."""
        if not self.access_token:
            raise Exception("Not authenticated. Please authenticate first.")
        
        # Check if token is expired or about to expire (within 5 minutes)
        if self.token_expires_at and datetime.now(timezone.utc) >= (self.token_expires_at - timedelta(minutes=5)):
            if self.refresh_token:
                self._refresh_access_token()
            else:
                raise Exception("Access token expired and no refresh token available. Please re-authenticate.")
    
    def _refresh_access_token(self):
        """Refresh the access token using the refresh token."""
        if not self.refresh_token:
            raise Exception("No refresh token available")
        
        credentials_path = Path(__file__).parent / "credentials.json"
        if not credentials_path.exists():
            raise Exception("credentials.json not found. Please add your WHOOP API credentials.")
        
        with open(credentials_path, 'r') as f:
            credentials = json.load(f)
        
        client_id = credentials.get("client_id")
        client_secret = credentials.get("client_secret")
        
        if not client_id or not client_secret:
            raise Exception("client_id and client_secret must be set in credentials.json")
        
        try:
            response = requests.post(
                WHOOP_AUTH_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret
                }
            )
            response.raise_for_status()
            token_data = response.json()
            self._save_tokens(
                token_data["access_token"],
                token_data.get("refresh_token", self.refresh_token),
                token_data.get("expires_in", 3600)
            )
            logger.info("WHOOP access token refreshed successfully")
        except Exception as e:
            logger.error(f"Error refreshing token: {e}")
            raise Exception(f"Failed to refresh access token: {str(e)}")
    
    def get_authorization_url(self, state: str) -> Optional[str]:
        """Get OAuth authorization URL for web-based authentication."""
        credentials_path = Path(__file__).parent / "credentials.json"
        if not credentials_path.exists():
            logger.warning("WHOOP credentials.json not found")
            return None
        
        try:
            with open(credentials_path, 'r') as f:
                credentials = json.load(f)
            
            client_id = credentials.get("client_id")
            if not client_id:
                logger.error("client_id not found in credentials.json")
                return None
            
            from flask import request
            scheme = request.headers.get('X-Forwarded-Proto', request.scheme)
            host = request.headers.get('X-Forwarded-Host', request.host)
            base_url = f"{scheme}://{host}"
            redirect_uri = f"{base_url}/api/plugins/whoop/auth/callback"
            
            # Store state for callback verification
            from flask import current_app
            if hasattr(current_app, 'oauth_flows'):
                current_app.oauth_flows[state] = {
                    'plugin_name': 'whoop',
                    'redirect_uri': redirect_uri,
                    'client_id': client_id
                }
            
            auth_url = (
                f"{WHOOP_AUTHORIZE_URL}?"
                f"response_type=code&"
                f"client_id={client_id}&"
                f"redirect_uri={redirect_uri}&"
                f"scope=read:recovery%20read:workout%20read:sleep%20read:profile&"
                f"state={state}"
            )
            return auth_url
        except Exception as e:
            logger.error(f"Error generating authorization URL: {e}", exc_info=True)
            return None
    
    def complete_authorization(self, code: str, state: str) -> bool:
        """Complete OAuth flow with authorization code."""
        try:
            from flask import current_app
            oauth_data = None
            if hasattr(current_app, 'oauth_flows') and state in current_app.oauth_flows:
                oauth_data = current_app.oauth_flows[state]
            
            if not oauth_data:
                logger.error("OAuth state not found")
                return False
            
            credentials_path = Path(__file__).parent / "credentials.json"
            if not credentials_path.exists():
                logger.error("credentials.json not found")
                return False
            
            with open(credentials_path, 'r') as f:
                credentials = json.load(f)
            
            client_id = credentials.get("client_id")
            client_secret = credentials.get("client_secret")
            
            if not client_id or not client_secret:
                logger.error("client_id and client_secret must be set in credentials.json")
                return False
            
            redirect_uri = oauth_data.get("redirect_uri")
            
            # Exchange authorization code for tokens
            response = requests.post(
                WHOOP_AUTH_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": client_id,
                    "client_secret": client_secret
                }
            )
            response.raise_for_status()
            token_data = response.json()
            
            self._save_tokens(
                token_data["access_token"],
                token_data.get("refresh_token"),
                token_data.get("expires_in", 3600)
            )
            
            logger.info("WHOOP authorization completed successfully")
            return True
        except Exception as e:
            logger.error(f"Error completing authorization: {e}", exc_info=True)
            return False
    
    def _make_api_request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Make an authenticated API request to WHOOP."""
        self._ensure_authenticated()
        
        url = f"{WHOOP_API_BASE}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                # Token might be expired, try refreshing
                self._refresh_access_token()
                headers["Authorization"] = f"Bearer {self.access_token}"
                response = requests.get(url, headers=headers, params=params)
                response.raise_for_status()
                return response.json()
            raise
        except Exception as e:
            logger.error(f"Error making API request to {endpoint}: {e}")
            raise
    
    def fetch_data(self) -> List[Dict[str, Any]]:
        """Fetch WHOOP health data for the configured time period."""
        if not self.access_token:
            raise Exception("Not authenticated. Please authenticate first.")
        
        days_back = self.config.get("days_back", 365)
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days_back)
        
        logger.info(f"Fetching WHOOP data from {start_date.date()} to {end_date.date()}")
        
        results = []
        
        try:
            # Get user profile first
            profile = self._make_api_request("/developer/v1/user/profile/basic")
            user_id = profile.get("user_id")
            if not user_id:
                raise Exception("Could not get user ID from profile")
            
            logger.info(f"WHOOP user ID: {user_id}")
            
            # Fetch data for each day in the range
            current_date = start_date
            while current_date <= end_date:
                date_str = current_date.strftime("%Y-%m-%d")
                
                # Fetch recovery data
                try:
                    recovery = self._make_api_request(
                        f"/developer/v1/recovery",
                        params={"start": date_str, "end": date_str}
                    )
                    if recovery and len(recovery) > 0:
                        recovery_data = recovery[0]
                        results.append({
                            "source_id": f"recovery_{date_str}",
                            "item_type": "whoop_recovery",
                            "title": f"Recovery - {date_str}",
                            "content": self._format_recovery_data(recovery_data),
                            "metadata": {
                                "date": date_str,
                                "recovery_score": recovery_data.get("score", {}).get("recovery_score"),
                                "resting_heart_rate": recovery_data.get("score", {}).get("resting_heart_rate"),
                                "hrv": recovery_data.get("score", {}).get("hrv_milli")
                            },
                            "source_timestamp": current_date.replace(hour=0, minute=0, second=0)
                        })
                except Exception as e:
                    logger.warning(f"Error fetching recovery for {date_str}: {e}")
                
                # Fetch sleep data
                try:
                    sleep = self._make_api_request(
                        f"/developer/v1/cycle/sleep",
                        params={"start": date_str, "end": date_str}
                    )
                    if sleep and len(sleep) > 0:
                        sleep_data = sleep[0]
                        results.append({
                            "source_id": f"sleep_{date_str}",
                            "item_type": "whoop_sleep",
                            "title": f"Sleep - {date_str}",
                            "content": self._format_sleep_data(sleep_data),
                            "metadata": {
                                "date": date_str,
                                "sleep_score": sleep_data.get("score", {}).get("stage_summary", {}).get("total_sleep_need_score"),
                                "total_sleep_ms": sleep_data.get("score", {}).get("stage_summary", {}).get("total_sleep_milli"),
                                "sleep_efficiency": sleep_data.get("score", {}).get("sleep_efficiency_percentage")
                            },
                            "source_timestamp": current_date.replace(hour=0, minute=0, second=0)
                        })
                except Exception as e:
                    logger.warning(f"Error fetching sleep for {date_str}: {e}")
                
                # Fetch workout/strain data
                try:
                    workouts = self._make_api_request(
                        f"/developer/v1/cycle/workout",
                        params={"start": date_str, "end": date_str}
                    )
                    if workouts:
                        for workout in workouts:
                            results.append({
                                "source_id": f"workout_{workout.get('id')}",
                                "item_type": "whoop_workout",
                                "title": f"Workout - {date_str}",
                                "content": self._format_workout_data(workout),
                                "metadata": {
                                    "date": date_str,
                                    "strain_score": workout.get("score", {}).get("strain"),
                                    "sport_id": workout.get("sport_id"),
                                    "workout_id": workout.get("id")
                                },
                                "source_timestamp": datetime.fromisoformat(workout.get("start", date_str).replace("Z", "+00:00")) if workout.get("start") else current_date
                            })
                except Exception as e:
                    logger.warning(f"Error fetching workouts for {date_str}: {e}")
                
                # Move to next day
                current_date += timedelta(days=1)
                
                # Log progress every 30 days
                if (current_date - start_date).days % 30 == 0:
                    logger.info(f"Processed {(current_date - start_date).days} days...")
            
            logger.info(f"Successfully fetched {len(results)} WHOOP data items")
            return results
            
        except Exception as e:
            logger.error(f"Error fetching WHOOP data: {e}", exc_info=True)
            raise Exception(f"Error fetching WHOOP data: {str(e)}")
    
    def _format_recovery_data(self, recovery: Dict) -> str:
        """Format recovery data as text."""
        score = recovery.get("score", {})
        lines = [
            f"Recovery Score: {score.get('recovery_score')}",
            f"Resting Heart Rate: {score.get('resting_heart_rate')} bpm",
            f"HRV: {score.get('hrv_milli')} ms" if score.get('hrv_milli') else "HRV: N/A",
            f"Skin Temperature: {score.get('skin_temp_celsius')}°C" if score.get('skin_temp_celsius') else "",
            f"SpO2: {score.get('spo2_percentage')}%" if score.get('spo2_percentage') else "",
        ]
        return "\n".join([line for line in lines if line])
    
    def _format_sleep_data(self, sleep: Dict) -> str:
        """Format sleep data as text."""
        score = sleep.get("score", {})
        stage_summary = score.get("stage_summary", {})
        lines = [
            f"Total Sleep: {stage_summary.get('total_sleep_milli', 0) / 3600000:.2f} hours",
            f"Sleep Efficiency: {score.get('sleep_efficiency_percentage')}%",
            f"Time in Bed: {stage_summary.get('total_in_bed_milli', 0) / 3600000:.2f} hours",
            f"Awake Time: {stage_summary.get('total_awake_milli', 0) / 3600000:.2f} hours",
            f"Light Sleep: {stage_summary.get('total_light_sleep_milli', 0) / 3600000:.2f} hours",
            f"Slow Wave Sleep: {stage_summary.get('total_slow_wave_sleep_milli', 0) / 3600000:.2f} hours",
            f"REM Sleep: {stage_summary.get('total_rem_sleep_milli', 0) / 3600000:.2f} hours",
        ]
        return "\n".join([line for line in lines if line])
    
    def _format_workout_data(self, workout: Dict) -> str:
        """Format workout/strain data as text."""
        score = workout.get("score", {})
        lines = [
            f"Strain Score: {score.get('strain')}",
            f"Average Heart Rate: {score.get('average_heart_rate')} bpm" if score.get('average_heart_rate') else "",
            f"Max Heart Rate: {score.get('max_heart_rate')} bpm" if score.get('max_heart_rate') else "",
            f"Calories: {score.get('kilojoule', 0) / 4.184:.0f} kcal" if score.get('kilojoule') else "",
            f"Duration: {score.get('duration', 0) / 60:.1f} minutes" if score.get('duration') else "",
            f"Sport: {workout.get('sport', {}).get('name', 'Unknown')}" if workout.get('sport') else "",
        ]
        return "\n".join([line for line in lines if line])
    
    def test_connection(self) -> bool:
        """Test WHOOP connection."""
        try:
            if not self.access_token:
                return False
            self._ensure_authenticated()
            profile = self._make_api_request("/developer/v1/user/profile/basic")
            return profile is not None and "user_id" in profile
        except Exception as e:
            logger.error(f"WHOOP connection test failed: {e}")
            return False
    
    def get_config_schema(self) -> Dict[str, Any]:
        """Return configuration schema."""
        schema = super().get_config_schema()
        schema["days_back"] = {
            "type": "integer",
            "default": 365,
            "description": "Number of days back to fetch data (default: 365)"
        }
        return schema

