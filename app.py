"""Main Flask application."""
from flask import Flask, jsonify, request, render_template_string, send_file, redirect, url_for
from flask_cors import CORS
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from database import ImportLog, DataItem, SessionLocal, init_db
from importer import DataImporter
from scheduler import ImportScheduler
from plugin_loader import PluginLoader
import config
import logging
from pathlib import Path
import secrets

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Store OAuth flows temporarily (in production, use Redis or similar)
oauth_flows = {}
app.oauth_flows = oauth_flows  # Make accessible to plugins

# Initialize services
init_db()
importer = DataImporter()
plugin_loader = PluginLoader()
scheduler = ImportScheduler()
scheduler.start()


@app.route("/")
def index():
    """Serve the main UI."""
    return render_template_string(open("templates/index.html").read())


@app.route("/api/plugins", methods=["GET"])
def list_plugins():
    """List all available plugins."""
    db = SessionLocal()
    try:
        plugins = plugin_loader.get_all_plugins()
        result = []
        for name, plugin in plugins.items():
            # Get last import time for this plugin
            last_import = db.query(ImportLog).filter(
                ImportLog.plugin_name == name,
                ImportLog.status == "success"
            ).order_by(ImportLog.completed_at.desc()).first()
            
            last_import_time = None
            last_import_records = None
            if last_import and last_import.completed_at:
                last_import_time = last_import.completed_at.isoformat()
                last_import_records = last_import.records_imported
            
            # Check authentication status and last auth time
            auth_status = None
            last_auth_time = None
            plugin_dir = config.PLUGINS_DIR / name
            token_path = plugin_dir / "token.json"
            
            if token_path.exists():
                try:
                    # Get file modification time (when token was last saved/updated)
                    import os
                    from datetime import datetime, timezone
                    mtime = os.path.getmtime(token_path)
                    last_auth_time = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
                    
                    # Try to check if token is valid by checking if plugin can authenticate
                    if hasattr(plugin, '_authenticate'):
                        try:
                            # Just check if service exists or token is readable
                            from google.oauth2.credentials import Credentials
                            # Check if plugin has SCOPES attribute (Google OAuth plugins)
                            scopes = getattr(plugin, 'SCOPES', None)
                            if scopes:
                                creds = Credentials.from_authorized_user_file(str(token_path), scopes)
                                if creds and creds.valid:
                                    auth_status = "authenticated"
                                elif creds and creds.expired and creds.refresh_token:
                                    auth_status = "expired"  # Can be refreshed
                                else:
                                    auth_status = "invalid"
                            else:
                                auth_status = "authenticated"  # Token file exists, assume valid
                        except Exception as e:
                            logger.debug(f"Error validating token for {name}: {e}")
                            auth_status = "invalid"
                    else:
                        auth_status = "authenticated"  # Token file exists
                except Exception as e:
                    logger.warning(f"Error checking auth status for {name}: {e}")
                    auth_status = "unknown"
            else:
                auth_status = "not_authenticated"
            
            result.append({
                "name": name,
                "enabled": plugin.config.get("enabled", False),
                "config_schema": plugin.get_config_schema(),
                "last_import_time": last_import_time,
                "last_import_records": last_import_records,
                "auth_status": auth_status,
                "last_auth_time": last_auth_time
            })
        return jsonify(result)
    finally:
        db.close()


@app.route("/api/imports", methods=["GET"])
def list_imports():
    """List import logs."""
    db = SessionLocal()
    try:
        limit = request.args.get("limit", 50, type=int)
        plugin_name = request.args.get("plugin", None)
        
        query = db.query(ImportLog)
        if plugin_name:
            query = query.filter(ImportLog.plugin_name == plugin_name)
        
        logs = query.order_by(ImportLog.started_at.desc()).limit(limit).all()
        
        result = []
        for log in logs:
            result.append({
                "id": log.id,
                "plugin_name": log.plugin_name,
                "status": log.status,
                "started_at": log.started_at.isoformat() if log.started_at else None,
                "completed_at": log.completed_at.isoformat() if log.completed_at else None,
                "records_imported": log.records_imported,
                "error_message": log.error_message
            })
        
        return jsonify(result)
    finally:
        db.close()


@app.route("/api/imports/run", methods=["POST"])
def run_import():
    """Run import for a specific plugin or all plugins."""
    data = request.get_json() or {}
    plugin_name = data.get("plugin_name")
    
    if plugin_name:
        log_entry = importer.import_from_plugin(plugin_name)
        return jsonify({
            "success": log_entry.status == "success",
            "plugin_name": log_entry.plugin_name,
            "status": log_entry.status,
            "records_imported": log_entry.records_imported,
            "error_message": log_entry.error_message
        })
    else:
        results = importer.import_all()
        return jsonify({
            "success": True,
            "results": {
                name: {
                    "status": log.status,
                    "records_imported": log.records_imported,
                    "error_message": log.error_message
                }
                for name, log in results.items()
            }
        })


@app.route("/api/plugins/<plugin_name>/context", methods=["GET"])
def get_plugin_context(plugin_name):
    """Get context data from a specific plugin for Custom GPT."""
    db = SessionLocal()
    try:
        # Get query parameters
        limit = request.args.get("limit", 50, type=int)
        days = request.args.get("days", 30, type=int)
        item_type = request.args.get("item_type", None)
        query = request.args.get("query", None)  # Optional text search
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        # Query data items
        db_query = db.query(DataItem).filter(
            DataItem.plugin_name == plugin_name,
            DataItem.created_at >= cutoff_date
        )
        
        if item_type:
            db_query = db_query.filter(DataItem.item_type == item_type)
        
        # Simple text search in title and content
        if query:
            db_query = db_query.filter(
                (DataItem.title.contains(query)) | 
                (DataItem.content.contains(query))
            )
        
        items = db_query.order_by(DataItem.created_at.desc()).limit(limit).all()
        
        # Format response
        result = {
            "plugin_name": plugin_name,
            "count": len(items),
            "items": [],
            "message": "No data found. Run an import first from the 'Run Imports' tab." if len(items) == 0 else None
        }
        
        for item in items:
            result["items"].append({
                "id": item.id,
                "type": item.item_type,
                "title": item.title,
                "content": item.content,
                "metadata": item.item_metadata,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "source_timestamp": item.source_timestamp.isoformat() if item.source_timestamp else None
            })
        
        return jsonify(result)
    finally:
        db.close()


@app.route("/api/plugins/<plugin_name>/search", methods=["GET"])
def search_plugin_context(plugin_name):
    """Search context data from a specific plugin."""
    query = request.args.get("q", "")
    if not query:
        return jsonify({"error": "Missing 'q' parameter"}), 400
    
    db = SessionLocal()
    try:
        limit = request.args.get("limit", 20, type=int)
        days = request.args.get("days", 30, type=int)
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        items = db.query(DataItem).filter(
            DataItem.plugin_name == plugin_name,
            DataItem.created_at >= cutoff_date,
            (DataItem.title.contains(query)) | 
            (DataItem.content.contains(query))
        ).order_by(DataItem.created_at.desc()).limit(limit).all()
        
        result = {
            "plugin_name": plugin_name,
            "query": query,
            "count": len(items),
            "items": [],
            "message": "No data found. Run an import first from the 'Run Imports' tab." if len(items) == 0 else None
        }
        
        for item in items:
            result["items"].append({
                "id": item.id,
                "type": item.item_type,
                "title": item.title,
                "content": item.content[:500],  # Truncate for search results
                "created_at": item.created_at.isoformat() if item.created_at else None
            })
        
        return jsonify(result)
    finally:
        db.close()


@app.route("/api/plugins/<plugin_name>/schema", methods=["GET"])
def get_plugin_schema(plugin_name):
    """Download the Custom GPT schema JSON file for a plugin."""
    schema_path = config.PLUGINS_DIR / plugin_name / "custom_gpt_schema.json"
    
    if not schema_path.exists():
        return jsonify({"error": f"Schema file not found for plugin: {plugin_name}"}), 404
    
    try:
        return send_file(
            str(schema_path),
            mimetype='application/json',
            as_attachment=True,
            download_name=f"{plugin_name}_custom_gpt_schema.json"
        )
    except Exception as e:
        logger.error(f"Error serving schema file: {e}")
        return jsonify({"error": "Failed to serve schema file"}), 500


@app.route("/api/plugins/<plugin_name>/auth/start", methods=["POST"])
def start_plugin_auth(plugin_name):
    """Start OAuth flow for a plugin and return authorization URL."""
    plugin = plugin_loader.get_plugin(plugin_name)
    if not plugin:
        return jsonify({"error": f"Plugin {plugin_name} not found"}), 404
    
    # Check if plugin supports OAuth
    if not hasattr(plugin, 'get_authorization_url'):
        return jsonify({"error": f"Plugin {plugin_name} does not support OAuth authentication"}), 400
    
    try:
        # Generate a state token for security
        state = secrets.token_urlsafe(32)
        
        # Get authorization URL from plugin
        auth_url = plugin.get_authorization_url(state)
        
        if not auth_url:
            return jsonify({"error": "Failed to generate authorization URL"}), 500
        
        # Get redirect URI from stored flow (plugin stores it there)
        redirect_uri = None
        if state in oauth_flows and 'redirect_uri' in oauth_flows[state]:
            redirect_uri = oauth_flows[state]['redirect_uri']
        
        # Ensure state is stored for verification (plugin may have already stored it)
        if state not in oauth_flows:
            oauth_flows[state] = {
                "plugin_name": plugin_name,
                "timestamp": datetime.now(timezone.utc)
            }
        else:
            # Update with plugin name if not set
            oauth_flows[state]["plugin_name"] = plugin_name
            oauth_flows[state]["timestamp"] = datetime.now(timezone.utc)
        
        return jsonify({
            "authorization_url": auth_url,
            "state": state,
            "redirect_uri": redirect_uri,
            "instructions": f"Make sure this redirect URI is added to your Google Cloud Console OAuth credentials: {redirect_uri}" if redirect_uri else None
        })
    except Exception as e:
        logger.error(f"Error starting OAuth flow: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/plugins/<plugin_name>/auth/callback", methods=["GET"])
def plugin_auth_callback(plugin_name):
    """Handle OAuth callback."""
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')
    
    if error:
        error_description = request.args.get('error_description', '')
        redirect_uri_info = ""
        test_user_info = ""
        
        # Check if it's an access_denied error (test user issue)
        if error == 'access_denied' or 'verification process' in error_description.lower() or 'test user' in error_description.lower():
            test_user_info = """
                <h2>OAuth Consent Screen - Add Test User</h2>
                <p style="color: red; font-weight: bold;">⚠️ Your app is in "Testing" mode and your email is not in the test users list.</p>
                <p>To fix this:</p>
                <ol>
                    <li>Go to <a href="https://console.cloud.google.com/" target="_blank">Google Cloud Console</a></li>
                    <li>Navigate to: <strong>APIs & Services > OAuth consent screen</strong></li>
                    <li>Scroll down to the <strong>"Test users"</strong> section</li>
                    <li>Click <strong>"ADD USERS"</strong></li>
                    <li>Add your Gmail address (the one you're trying to authenticate with, e.g., <code>your-email@gmail.com</code>)</li>
                    <li>Click <strong>"ADD"</strong></li>
                    <li>Try authenticating again</li>
                </ol>
                <p><strong>Note:</strong> The app is in "Testing" mode, so only approved test users can authenticate. 
                You can add up to 100 test users. To allow anyone to use it, you'd need to publish the app 
                (requires verification for sensitive scopes like Gmail).</p>
            """
        
        if state in oauth_flows and 'redirect_uri' in oauth_flows[state]:
            redirect_uri = oauth_flows[state]['redirect_uri']
            redirect_uri_info = f"""
                <h2>Redirect URI Configuration</h2>
                <p><strong>Copy this EXACT URL and add it to Google Cloud Console:</strong></p>
                <code style="background: #f4f4f4; padding: 10px; display: block; margin: 10px 0; font-size: 14px; word-break: break-all;">
                    {redirect_uri}
                </code>
                <p style="color: red; font-weight: bold;">⚠️ IMPORTANT: This URL must start with https:// (not http://)</p>
                <p>If it starts with http://, you need to set up HTTPS first (see instructions below).</p>
                <p>Add this URL to Google Cloud Console:</p>
                <ol>
                    <li>Go to <a href="https://console.cloud.google.com/" target="_blank">Google Cloud Console</a></li>
                    <li>Navigate to: APIs & Services > Credentials</li>
                    <li>Click on your OAuth 2.0 Client ID</li>
                    <li><strong>Important:</strong> Make sure your OAuth client type is "Web application" (not "Desktop app")</li>
                    <li>If it's "Desktop app", you need to create a new "Web application" OAuth client</li>
                    <li>Under "Authorized redirect URIs", click "ADD URI"</li>
                    <li>Paste the redirect URI above</li>
                    <li>Click "SAVE"</li>
                </ol>
                <p><strong>Note:</strong> If you don't see "Authorized redirect URIs", your OAuth client is likely set as "Desktop app". 
                You need to create a new OAuth client with type "Web application" to use web-based authentication.</p>
                <h2>HTTPS Setup Required</h2>
                <p><strong>Google requires HTTPS for Gmail API.</strong> If the redirect URI above starts with <code>http://</code>, you need HTTPS.</p>
                <p><strong>Production Setup:</strong> Set up Nginx with Let's Encrypt (see README.md for full instructions)</p>
                <ol>
                    <li>Run: <code>sudo ./setup_nginx.sh your-domain.com</code></li>
                    <li>Run: <code>sudo ./setup_ssl.sh your-domain.com</code></li>
                    <li>Add the redirect URI to Google Cloud Console: <code>https://your-domain.com/api/plugins/gmail_personal/auth/callback</code></li>
                </ol>
            """
        
        return render_template_string("""
            <html>
                <head><title>Authentication Error</title></head>
                <body style="font-family: Arial, sans-serif; padding: 20px; max-width: 800px; margin: 0 auto;">
                    <h1>Authentication Failed</h1>
                    <p><strong>Error:</strong> {{ error }}</p>
                    {% if error_description %}
                    <p><strong>Details:</strong> {{ error_description }}</p>
                    {% endif %}
                    {{ test_user_info|safe }}
                    {{ redirect_uri_info|safe }}
                    <p style="margin-top: 20px;">You can close this window.</p>
                    <script>
                        setTimeout(function() {
                            window.close();
                        }, 30000);
                    </script>
                </body>
            </html>
        """, error=error, error_description=error_description, redirect_uri_info=redirect_uri_info, test_user_info=test_user_info)
    
    if not code or not state:
        return render_template_string("""
            <html>
                <head><title>Authentication Error</title></head>
                <body>
                    <h1>Authentication Failed</h1>
                    <p>Missing authorization code or state.</p>
                    <p>You can close this window.</p>
                </body>
            </html>
        """)
    
    # Verify state
    if state not in oauth_flows:
        return render_template_string("""
            <html>
                <head><title>Authentication Error</title></head>
                <body>
                    <h1>Authentication Failed</h1>
                    <p>Invalid state token. Please try again.</p>
                    <p>You can close this window.</p>
                </body>
            </html>
        """)
    
    flow_info = oauth_flows[state]
    if flow_info["plugin_name"] != plugin_name:
        return render_template_string("""
            <html>
                <head><title>Authentication Error</title></head>
                <body>
                    <h1>Authentication Failed</h1>
                    <p>Plugin mismatch.</p>
                    <p>You can close this window.</p>
                </body>
            </html>
        """)
    
    plugin = plugin_loader.get_plugin(plugin_name)
    if not plugin:
        return render_template_string("""
            <html>
                <head><title>Authentication Error</title></head>
                <body>
                    <h1>Authentication Failed</h1>
                    <p>Plugin not found.</p>
                    <p>You can close this window.</p>
                </body>
            </html>
        """)
    
    try:
        # Store flow in oauth_flows if plugin stored it there
        if state in oauth_flows and 'flow' in oauth_flows[state]:
            # Flow is already stored, plugin can access it
            pass
        
        # Complete OAuth flow
        if hasattr(plugin, 'complete_authorization'):
            success = plugin.complete_authorization(code, state)
            if success:
                # Clean up state
                del oauth_flows[state]
                return render_template_string("""
                    <html>
                        <head><title>Authentication Success</title></head>
                        <body>
                            <h1>Authentication Successful!</h1>
                            <p>You have successfully authenticated {{ plugin_name }}.</p>
                            <p>You can close this window and return to the application.</p>
                            <script>
                                // Notify parent window if opened from popup
                                if (window.opener) {
                                    window.opener.postMessage({type: 'oauth_success', plugin: '{{ plugin_name }}'}, '*');
                                }
                                setTimeout(function() {
                                    window.close();
                                }, 2000);
                            </script>
                        </body>
                    </html>
                """, plugin_name=plugin_name)
            else:
                return render_template_string("""
                    <html>
                        <head><title>Authentication Error</title></head>
                        <body>
                            <h1>Authentication Failed</h1>
                            <p>Failed to complete authentication.</p>
                            <p>You can close this window.</p>
                        </body>
                    </html>
                """)
        else:
            return render_template_string("""
                <html>
                    <head><title>Authentication Error</title></head>
                    <body>
                        <h1>Authentication Failed</h1>
                        <p>Plugin does not support OAuth completion.</p>
                        <p>You can close this window.</p>
                    </body>
                </html>
            """)
    except Exception as e:
        logger.error(f"Error completing OAuth flow: {e}", exc_info=True)
        return render_template_string("""
            <html>
                <head><title>Authentication Error</title></head>
                <body>
                    <h1>Authentication Failed</h1>
                    <p>Error: {{ error }}</p>
                    <p>You can close this window.</p>
                </body>
            </html>
        """, error=str(e))


@app.route("/api/stats", methods=["GET"])
def get_stats():
    """Get statistics about imported data."""
    db = SessionLocal()
    try:
        total_items = db.query(DataItem).count()
        items_by_plugin = {}
        items_by_type = {}
        
        for item in db.query(DataItem).all():
            items_by_plugin[item.plugin_name] = items_by_plugin.get(item.plugin_name, 0) + 1
            items_by_type[item.item_type] = items_by_type.get(item.item_type, 0) + 1
        
        return jsonify({
            "total_items": total_items,
            "by_plugin": items_by_plugin,
            "by_type": items_by_type
        })
    finally:
        db.close()


if __name__ == "__main__":
    app.run(host=config.WEB_HOST, port=config.WEB_PORT, debug=False)

