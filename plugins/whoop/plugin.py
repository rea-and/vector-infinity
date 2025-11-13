"""Whoop health data plugin."""
from plugin_base import DataSourcePlugin
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Any


class Plugin(DataSourcePlugin):
    """Whoop health data source plugin."""
    
    def __init__(self):
        super().__init__("whoop")
    
    def fetch_data(self):
        """Fetch data from Whoop API."""
        api_key = self.config.get("api_key")
        if not api_key:
            raise Exception("Whoop API key not configured")
        
        days_back = self.config.get("days_back", 7)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)
        
        results = []
        
        # Whoop API endpoints (adjust based on actual API)
        base_url = "https://api.prod.whoop.com"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        try:
            # Fetch recovery data
            recovery_url = f"{base_url}/v1/recovery"
            recovery_params = {
                "start": start_date.isoformat(),
                "end": end_date.isoformat()
            }
            
            response = requests.get(recovery_url, headers=headers, params=recovery_params, timeout=30)
            if response.status_code == 200:
                recovery_data = response.json()
                for record in recovery_data.get("records", []):
                    results.append({
                        "source_id": f"recovery_{record.get('id', '')}",
                        "item_type": "health_data",
                        "title": f"Recovery: {record.get('score', {}).get('recovery_score', 'N/A')}%",
                        "content": f"Recovery Score: {record.get('score', {}).get('recovery_score', 'N/A')}%\n"
                                  f"HRV: {record.get('score', {}).get('hrv', 'N/A')}\n"
                                  f"RHR: {record.get('score', {}).get('resting_heart_rate', 'N/A')}",
                        "metadata": record,
                        "source_timestamp": datetime.fromisoformat(record.get("created_at", "").replace('Z', '+00:00')) if record.get("created_at") else None
                    })
            
            # Fetch workout data
            workout_url = f"{base_url}/v1/workout"
            workout_params = {
                "start": start_date.isoformat(),
                "end": end_date.isoformat()
            }
            
            response = requests.get(workout_url, headers=headers, params=workout_params, timeout=30)
            if response.status_code == 200:
                workout_data = response.json()
                for record in workout_data.get("records", []):
                    results.append({
                        "source_id": f"workout_{record.get('id', '')}",
                        "item_type": "health_data",
                        "title": f"Workout: {record.get('sport', {}).get('name', 'Unknown')}",
                        "content": f"Sport: {record.get('sport', {}).get('name', 'Unknown')}\n"
                                  f"Strain: {record.get('score', {}).get('strain', 'N/A')}\n"
                                  f"Calories: {record.get('score', {}).get('kilojoule', 0) / 4.184:.0f}",
                        "metadata": record,
                        "source_timestamp": datetime.fromisoformat(record.get("created_at", "").replace('Z', '+00:00')) if record.get("created_at") else None
                    })
            
            # Fetch sleep data
            sleep_url = f"{base_url}/v1/sleep"
            sleep_params = {
                "start": start_date.isoformat(),
                "end": end_date.isoformat()
            }
            
            response = requests.get(sleep_url, headers=headers, params=sleep_params, timeout=30)
            if response.status_code == 200:
                sleep_data = response.json()
                for record in sleep_data.get("records", []):
                    results.append({
                        "source_id": f"sleep_{record.get('id', '')}",
                        "item_type": "health_data",
                        "title": f"Sleep: {record.get('score', {}).get('sleep_performance_percentage', 'N/A')}%",
                        "content": f"Sleep Performance: {record.get('score', {}).get('sleep_performance_percentage', 'N/A')}%\n"
                                  f"Duration: {record.get('score', {}).get('total_sleep_time_milli', 0) / 3600000:.1f} hours\n"
                                  f"Efficiency: {record.get('score', {}).get('sleep_efficiency_percentage', 'N/A')}%",
                        "metadata": record,
                        "source_timestamp": datetime.fromisoformat(record.get("created_at", "").replace('Z', '+00:00')) if record.get("created_at") else None
                    })
        
        except requests.exceptions.RequestException as e:
            raise Exception(f"Error fetching Whoop data: {str(e)}")
        except Exception as e:
            raise Exception(f"Error processing Whoop data: {str(e)}")
        
        return results
    
    def test_connection(self):
        """Test Whoop API connection."""
        try:
            api_key = self.config.get("api_key")
            if not api_key:
                return False
            
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            response = requests.get(
                "https://api.prod.whoop.com/v1/user/profile/basic",
                headers=headers,
                timeout=10
            )
            return response.status_code == 200
        except:
            return False
    
    def get_config_schema(self):
        """Get configuration schema."""
        schema = super().get_config_schema()
        schema.update({
            "api_key": {
                "type": "string",
                "default": "",
                "description": "Whoop API key"
            },
            "days_back": {
                "type": "number",
                "default": 7,
                "description": "Number of days to look back"
            }
        })
        return schema

