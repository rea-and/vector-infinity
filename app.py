"""Main Flask application."""
from flask import Flask, jsonify, request, render_template_string, send_file, redirect, url_for, Response
import tempfile
import os
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
        # Get all loaded plugins
        loaded_plugins = plugin_loader.get_all_plugins()
        
        # Also check all plugin directories (even if not loaded/enabled)
        all_plugin_dirs = [d for d in config.PLUGINS_DIR.iterdir() if d.is_dir() and (d / "plugin.py").exists()]
        all_plugin_names = set([d.name for d in all_plugin_dirs])
        all_plugin_names.update(loaded_plugins.keys())
        
        result = []
        for name in all_plugin_names:
            plugin = loaded_plugins.get(name)
            
            # Get plugin config (even if not loaded)
            plugin_dir = config.PLUGINS_DIR / name
            config_path = plugin_dir / "config.json"
            enabled = False
            config_schema = {}
            
            if config_path.exists():
                import json
                try:
                    with open(config_path, 'r') as f:
                        plugin_config = json.load(f)
                        enabled = plugin_config.get("enabled", False)
                except:
                    pass
            
            # Get config schema from plugin if available, otherwise empty
            if plugin:
                config_schema = plugin.get_config_schema()
            
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
            token_path = plugin_dir / "token.json"
            
            if token_path.exists():
                try:
                    # Get file modification time (when token was last saved/updated)
                    import os
                    from datetime import datetime, timezone
                    mtime = os.path.getmtime(token_path)
                    last_auth_time = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
                    
                    # Try to check if token is valid
                    # First, try to get SCOPES from the plugin module
                    scopes = None
                    if plugin and hasattr(plugin, 'SCOPES'):
                        scopes = plugin.SCOPES
                    else:
                        # Try to import the plugin module to get SCOPES
                        try:
                            plugin_file = plugin_dir / "plugin.py"
                            if plugin_file.exists():
                                import importlib.util
                                spec = importlib.util.spec_from_file_location(
                                    f"plugins.{name}.plugin",
                                    plugin_file
                                )
                                if spec and spec.loader:
                                    module = importlib.util.module_from_spec(spec)
                                    spec.loader.exec_module(module)
                                    if hasattr(module, 'SCOPES'):
                                        scopes = module.SCOPES
                        except:
                            pass
                    
                    if scopes:
                        try:
                            from google.oauth2.credentials import Credentials
                            creds = Credentials.from_authorized_user_file(str(token_path), scopes)
                            if creds and creds.valid:
                                auth_status = "authenticated"
                            elif creds and creds.expired and creds.refresh_token:
                                auth_status = "expired"  # Can be refreshed
                            else:
                                auth_status = "invalid"
                        except Exception as e:
                            logger.debug(f"Error validating token for {name}: {e}")
                            auth_status = "invalid"
                    else:
                        # Token file exists but we can't validate it - assume authenticated
                        auth_status = "authenticated"
                except Exception as e:
                    logger.warning(f"Error checking auth status for {name}: {e}")
                    auth_status = "unknown"
            else:
                auth_status = "not_authenticated"
            
            result.append({
                "name": name,
                "enabled": enabled,
                "config_schema": config_schema,
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
    """Run import for a specific plugin or all plugins (async)."""
    plugin_name = None
    uploaded_file_path = None
    
    # Check if this is a file upload (multipart/form-data)
    if request.content_type and 'multipart/form-data' in request.content_type:
        plugin_name = request.form.get("plugin_name")
        if 'file' in request.files:
            file = request.files['file']
            if file.filename:
                # Save uploaded file to temporary location
                temp_dir = Path(tempfile.gettempdir()) / "vector_infinity_uploads"
                temp_dir.mkdir(exist_ok=True)
                uploaded_file_path = temp_dir / f"{plugin_name}_{secrets.token_hex(8)}_{file.filename}"
                file.save(str(uploaded_file_path))
                logger.info(f"Saved uploaded file to: {uploaded_file_path}")
    else:
        # JSON request
        data = request.get_json() or {}
        plugin_name = data.get("plugin_name")
    
    if plugin_name:
        # Create log entry first
        db = SessionLocal()
        try:
            log_entry = ImportLog(
                plugin_name=plugin_name,
                status="running",
                started_at=datetime.now(timezone.utc),
                progress_message="Starting import..."
            )
            db.add(log_entry)
            db.commit()
            log_id = log_entry.id
        finally:
            db.close()
        
        # Start import in background thread
        # Pass uploaded_file_path to the async function so it can set it on the plugin instance
        importer.import_from_plugin_async(plugin_name, log_id, uploaded_file_path=str(uploaded_file_path) if uploaded_file_path else None)
        
        return jsonify({
            "success": True,
            "log_id": log_id,
            "plugin_name": plugin_name,
            "status": "running",
            "message": "Import started in background"
        })
    else:
        # For "import all", run synchronously (could be improved later)
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


@app.route("/api/imports/<int:log_id>/status", methods=["GET"])
def get_import_status(log_id):
    """Get the current status of an import."""
    db = SessionLocal()
    try:
        log_entry = db.query(ImportLog).filter_by(id=log_id).first()
        if not log_entry:
            return jsonify({"error": "Import log not found"}), 404
        
        progress_percent = 0
        if log_entry.progress_total > 0:
            progress_percent = int((log_entry.progress_current / log_entry.progress_total) * 100)
        
        return jsonify({
            "id": log_entry.id,
            "plugin_name": log_entry.plugin_name,
            "status": log_entry.status,
            "records_imported": log_entry.records_imported or 0,
            "progress_current": log_entry.progress_current or 0,
            "progress_total": log_entry.progress_total or 0,
            "progress_percent": progress_percent,
            "progress_message": log_entry.progress_message or "",
            "error_message": log_entry.error_message,
            "started_at": log_entry.started_at.isoformat() if log_entry.started_at else None,
            "completed_at": log_entry.completed_at.isoformat() if log_entry.completed_at else None
        })
    finally:
        db.close()


@app.route("/api/chat/threads", methods=["POST"])
def create_chat_thread():
    """Create a new chat thread."""
    try:
        from assistant_service import AssistantService
        assistant_service = AssistantService()
        
        thread_id = assistant_service.create_thread()
        if not thread_id:
            return jsonify({"error": "Failed to create thread"}), 500
        
        return jsonify({"thread_id": thread_id})
    except Exception as e:
        logger.error(f"Error creating thread: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/chat/threads/<thread_id>/messages", methods=["POST"])
def send_chat_message(thread_id):
    """Send a message in a chat thread."""
    try:
        data = request.get_json() or {}
        message = data.get("message", "")
        
        if not message:
            return jsonify({"error": "message parameter is required"}), 400
        
        from assistant_service import AssistantService
        from vector_store_service import VectorStoreService
        
        assistant_service = AssistantService()
        vector_store_service = VectorStoreService()
        
        # Get unified vector store ID
        vector_store_id = vector_store_service.get_unified_vector_store_id()
        if not vector_store_id:
            return jsonify({"error": "No vector store found. Please run an import first."}), 404
        
        # Get or create unified assistant with vector store
        assistant_id = assistant_service.get_or_create_unified_assistant(vector_store_id)
        if not assistant_id:
            return jsonify({"error": "Failed to get or create assistant"}), 500
        
        # Send message and get response
        response = assistant_service.send_message(thread_id, assistant_id, message)
        if response is None:
            return jsonify({"error": "Failed to get response from assistant"}), 500
        
        return jsonify({
            "response": response,
            "thread_id": thread_id,
            "assistant_id": assistant_id
        })
    except Exception as e:
        logger.error(f"Error sending message: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/chat/threads/<thread_id>/messages", methods=["GET"])
def get_chat_messages(thread_id):
    """Get all messages from a chat thread."""
    try:
        from assistant_service import AssistantService
        assistant_service = AssistantService()
        
        messages = assistant_service.get_thread_messages(thread_id)
        return jsonify({"messages": messages})
    except Exception as e:
        logger.error(f"Error getting messages: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/vector-store/info", methods=["GET"])
def get_vector_store_info():
    """Get information about the unified vector store."""
    try:
        from vector_store_service import VectorStoreService
        vector_store_service = VectorStoreService()
        
        info = vector_store_service.get_vector_store_info()
        if not info:
            return jsonify({"error": "Vector store not found or not accessible"}), 404
        
        return jsonify(info)
    except Exception as e:
        logger.error(f"Error getting vector store info: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/vector-store/reupload", methods=["POST"])
def reupload_all_data_to_vector_store():
    """Re-upload all existing data from the database to the vector store."""
    try:
        from vector_store_service import VectorStoreService
        from database import DataItem, SessionLocal
        
        vector_store_service = VectorStoreService()
        db = SessionLocal()
        
        try:
            # Get all data items from database
            all_items = db.query(DataItem).all()
            
            if not all_items:
                return jsonify({"error": "No data items found in database"}), 404
            
            # Group by plugin
            items_by_plugin = {}
            for item in all_items:
                if item.plugin_name not in items_by_plugin:
                    items_by_plugin[item.plugin_name] = []
                
                items_by_plugin[item.plugin_name].append({
                    "source_id": item.source_id,
                    "item_type": item.item_type,
                    "title": item.title,
                    "content": item.content,
                    "metadata": item.item_metadata or {},
                    "source_timestamp": item.source_timestamp
                })
            
            # Upload each plugin's data
            total_uploaded = 0
            results = {}
            
            for plugin_name, items in items_by_plugin.items():
                logger.info(f"Re-uploading {len(items)} items from {plugin_name} to vector store")
                
                # Upload in batches
                batch_size = 100
                plugin_uploaded = 0
                
                for batch_start in range(0, len(items), batch_size):
                    batch_end = min(batch_start + batch_size, len(items))
                    batch_items = items[batch_start:batch_end]
                    
                    success = vector_store_service.upload_data_to_vector_store(plugin_name, batch_items)
                    if success:
                        plugin_uploaded += len(batch_items)
                        total_uploaded += len(batch_items)
                
                results[plugin_name] = {
                    "total_items": len(items),
                    "uploaded": plugin_uploaded
                }
            
            return jsonify({
                "success": True,
                "total_items": len(all_items),
                "total_uploaded": total_uploaded,
                "results": results
            })
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error re-uploading data to vector store: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


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


@app.route("/api/data/clear", methods=["POST"])
def clear_all_data():
    """Clear all imported data from the database."""
    db = SessionLocal()
    try:
        # Get confirmation from request
        data = request.get_json() or {}
        confirm = data.get("confirm", False)
        
        if not confirm:
            return jsonify({"error": "Confirmation required. Set 'confirm': true in request body."}), 400
        
        # Count items before deletion
        total_items = db.query(DataItem).count()
        
        # Delete all data items
        db.query(DataItem).delete()
        
        # Optionally clear import logs (commented out - uncomment if you want to clear logs too)
        # db.query(ImportLog).delete()
        
        db.commit()
        
        logger.info(f"Cleared {total_items} data items from database")
        
        return jsonify({
            "success": True,
            "message": f"Successfully cleared {total_items} data items from database",
            "items_deleted": total_items
        })
    except Exception as e:
        db.rollback()
        logger.error(f"Error clearing data: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/stats", methods=["GET"])
def get_stats():
    """Get statistics about imported data."""
    import os
    db = SessionLocal()
    try:
        total_items = db.query(DataItem).count()
        items_by_plugin = {}
        items_by_type = {}
        
        for item in db.query(DataItem).all():
            items_by_plugin[item.plugin_name] = items_by_plugin.get(item.plugin_name, 0) + 1
            items_by_type[item.item_type] = items_by_type.get(item.item_type, 0) + 1
        
        # Get database file size
        db_size_bytes = 0
        db_size_human = "0 B"
        if os.path.exists(config.DATABASE_PATH):
            db_size_bytes = os.path.getsize(config.DATABASE_PATH)
            # Convert to human-readable format
            size = float(db_size_bytes)
            for unit in ['B', 'KB', 'MB', 'GB']:
                if size < 1024.0:
                    db_size_human = f"{size:.2f} {unit}"
                    break
                size /= 1024.0
            else:
                db_size_human = f"{size:.2f} TB"
        
        return jsonify({
            "total_items": total_items,
            "by_plugin": items_by_plugin,
            "by_type": items_by_type,
            "database_size_bytes": db_size_bytes,
            "database_size": db_size_human
        })
    finally:
        db.close()


@app.route("/api/export/emails", methods=["GET"])
def export_emails():
    """Export all imported emails to a text file for ChatGPT knowledge upload."""
    db = SessionLocal()
    try:
        # Query all emails from gmail_personal plugin
        emails = db.query(DataItem).filter(
            DataItem.plugin_name == "gmail_personal",
            DataItem.item_type == "email"
        ).order_by(DataItem.source_timestamp.desc()).all()
        
        if not emails:
            return jsonify({"error": "No emails found to export"}), 404
        
        # Format emails for ChatGPT knowledge upload
        lines = []
        lines.append("=" * 80)
        lines.append("EMAIL EXPORT FOR CHATGPT KNOWLEDGE")
        lines.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        lines.append(f"Total Emails: {len(emails)}")
        lines.append("=" * 80)
        lines.append("")
        
        for idx, email in enumerate(emails, 1):
            lines.append(f"EMAIL #{idx}")
            lines.append("-" * 80)
            
            # Subject
            if email.title:
                lines.append(f"Subject: {email.title}")
            
            # Metadata
            if email.item_metadata:
                metadata = email.item_metadata
                if metadata.get("from"):
                    lines.append(f"From: {metadata['from']}")
                if metadata.get("to"):
                    lines.append(f"To: {metadata['to']}")
                if metadata.get("date"):
                    lines.append(f"Date: {metadata['date']}")
            
            # Source timestamp
            if email.source_timestamp:
                lines.append(f"Timestamp: {email.source_timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            
            # Content
            lines.append("")
            if email.content:
                # Remove "From: ..." prefix if it's already in metadata
                content = email.content
                if content.startswith("From:") and email.item_metadata and email.item_metadata.get("from"):
                    # Skip the "From: ..." line if it's redundant
                    lines_split = content.split("\n", 1)
                    if len(lines_split) > 1:
                        content = lines_split[1].strip()
                    else:
                        content = content
                
                lines.append("Content:")
                lines.append(content)
            
            lines.append("")
            lines.append("=" * 80)
            lines.append("")
        
        # Create text file content
        text_content = "\n".join(lines)
        
        # Return as downloadable text file
        response = Response(
            text_content,
            mimetype='text/plain',
            headers={
                'Content-Disposition': f'attachment; filename=emails_export_{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")}.txt'
            }
        )
        return response
        
    except Exception as e:
        logger.error(f"Error exporting emails: {e}", exc_info=True)
        return jsonify({"error": f"Error exporting emails: {str(e)}"}), 500
    finally:
        db.close()


@app.route("/api/export/whoop", methods=["GET"])
def export_whoop():
    """Export all imported WHOOP health data to a text file for ChatGPT knowledge upload."""
    db = SessionLocal()
    try:
        # Query all WHOOP data items
        whoop_items = db.query(DataItem).filter(
            DataItem.plugin_name == "whoop"
        ).order_by(DataItem.source_timestamp.desc()).all()
        
        if not whoop_items:
            return jsonify({"error": "No WHOOP data found to export"}), 404
        
        # Group by type for better organization
        recovery_items = [item for item in whoop_items if item.item_type == "whoop_recovery"]
        sleep_items = [item for item in whoop_items if item.item_type == "whoop_sleep"]
        workout_items = [item for item in whoop_items if item.item_type == "whoop_workout"]
        
        # Format WHOOP data for ChatGPT knowledge upload
        lines = []
        lines.append("=" * 80)
        lines.append("WHOOP HEALTH DATA EXPORT FOR CHATGPT KNOWLEDGE")
        lines.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        lines.append(f"Total Items: {len(whoop_items)}")
        lines.append(f"  - Recovery Records: {len(recovery_items)}")
        lines.append(f"  - Sleep Records: {len(sleep_items)}")
        lines.append(f"  - Workout Records: {len(workout_items)}")
        lines.append("=" * 80)
        lines.append("")
        
        # Export Recovery Data
        if recovery_items:
            lines.append("=" * 80)
            lines.append("RECOVERY DATA")
            lines.append("=" * 80)
            lines.append("")
            for idx, item in enumerate(sorted(recovery_items, key=lambda x: x.source_timestamp or datetime.min.replace(tzinfo=timezone.utc)), 1):
                lines.append(f"RECOVERY #{idx}")
                lines.append("-" * 80)
                
                if item.title:
                    lines.append(item.title)
                
                if item.source_timestamp:
                    lines.append(f"Date: {item.source_timestamp.strftime('%Y-%m-%d')}")
                
                if item.item_metadata:
                    metadata = item.item_metadata
                    if metadata.get("recovery_score") is not None:
                        lines.append(f"Recovery Score: {metadata['recovery_score']}")
                    if metadata.get("resting_heart_rate") is not None:
                        lines.append(f"Resting Heart Rate: {metadata['resting_heart_rate']} bpm")
                    if metadata.get("hrv") is not None:
                        lines.append(f"HRV: {metadata['hrv']} ms")
                
                if item.content:
                    lines.append("")
                    lines.append("Details:")
                    lines.append(item.content)
                
                lines.append("")
                lines.append("-" * 80)
                lines.append("")
        
        # Export Sleep Data
        if sleep_items:
            lines.append("=" * 80)
            lines.append("SLEEP DATA")
            lines.append("=" * 80)
            lines.append("")
            for idx, item in enumerate(sorted(sleep_items, key=lambda x: x.source_timestamp or datetime.min.replace(tzinfo=timezone.utc)), 1):
                lines.append(f"SLEEP #{idx}")
                lines.append("-" * 80)
                
                if item.title:
                    lines.append(item.title)
                
                if item.source_timestamp:
                    lines.append(f"Date: {item.source_timestamp.strftime('%Y-%m-%d')}")
                
                if item.item_metadata:
                    metadata = item.item_metadata
                    if metadata.get("sleep_score") is not None:
                        lines.append(f"Sleep Score: {metadata['sleep_score']}")
                    if metadata.get("total_sleep_ms") is not None:
                        hours = metadata['total_sleep_ms'] / 3600000
                        lines.append(f"Total Sleep: {hours:.2f} hours")
                    if metadata.get("sleep_efficiency") is not None:
                        lines.append(f"Sleep Efficiency: {metadata['sleep_efficiency']}%")
                
                if item.content:
                    lines.append("")
                    lines.append("Details:")
                    lines.append(item.content)
                
                lines.append("")
                lines.append("-" * 80)
                lines.append("")
        
        # Export Workout/Strain Data
        if workout_items:
            lines.append("=" * 80)
            lines.append("WORKOUT / STRAIN DATA")
            lines.append("=" * 80)
            lines.append("")
            for idx, item in enumerate(sorted(workout_items, key=lambda x: x.source_timestamp or datetime.min.replace(tzinfo=timezone.utc)), 1):
                lines.append(f"WORKOUT #{idx}")
                lines.append("-" * 80)
                
                if item.title:
                    lines.append(item.title)
                
                if item.source_timestamp:
                    lines.append(f"Date: {item.source_timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
                
                if item.item_metadata:
                    metadata = item.item_metadata
                    if metadata.get("strain_score") is not None:
                        lines.append(f"Strain Score: {metadata['strain_score']}")
                    if metadata.get("sport_id"):
                        lines.append(f"Sport ID: {metadata['sport_id']}")
                
                if item.content:
                    lines.append("")
                    lines.append("Details:")
                    lines.append(item.content)
                
                lines.append("")
                lines.append("-" * 80)
                lines.append("")
        
        # Create text file content
        text_content = "\n".join(lines)
        
        # Return as downloadable text file
        response = Response(
            text_content,
            mimetype='text/plain',
            headers={
                'Content-Disposition': f'attachment; filename=whoop_export_{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")}.txt'
            }
        )
        return response
        
    except Exception as e:
        logger.error(f"Error exporting WHOOP data: {e}", exc_info=True)
        return jsonify({"error": f"Error exporting WHOOP data: {str(e)}"}), 500
    finally:
        db.close()


if __name__ == "__main__":
    app.run(host=config.WEB_HOST, port=config.WEB_PORT, debug=False)

