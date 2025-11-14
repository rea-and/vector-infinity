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

# Initialize vector store service (optional, only if OPENAI_API_KEY is set)
vector_store_service = None
try:
    from vector_store_service import VectorStoreService
    vector_store_service = VectorStoreService()
    logger.info("Vector Store service initialized")
except Exception as e:
    logger.warning(f"Vector Store service not available (OPENAI_API_KEY may be missing): {e}")


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
            
            # Get vector store ID if available
            vector_store_id = None
            if vector_store_service:
                try:
                    vector_store_id = vector_store_service.get_store_id(name)
                except:
                    pass
            
            result.append({
                "name": name,
                "enabled": enabled,
                "config_schema": config_schema,
                "last_import_time": last_import_time,
                "last_import_records": last_import_records,
                "auth_status": auth_status,
                "last_auth_time": last_auth_time,
                "vector_store_id": vector_store_id
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
        importer.import_from_plugin_async(plugin_name, log_id)
        
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
        offset = request.args.get("offset", 0, type=int)  # Pagination offset
        
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
        
        # Get total count for pagination info
        total_count = db_query.count()
        
        # Apply pagination
        items = db_query.order_by(DataItem.created_at.desc()).offset(offset).limit(limit).all()
        
        # Format response
        result = {
            "plugin_name": plugin_name,
            "count": len(items),
            "total": total_count,
            "offset": offset,
            "limit": limit,
            "has_more": (offset + len(items)) < total_count,
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


@app.route("/api/plugins/<plugin_name>/semantic-search", methods=["POST"])
def semantic_search(plugin_name):
    """Semantic search endpoint for vector database (Action for Custom GPT)."""
    db = SessionLocal()
    try:
        data = request.get_json() or {}
        query = data.get("query", "")
        top_k = data.get("top_k", 5)
        
        if not query:
            return jsonify({"error": "query parameter is required"}), 400
        
        # Generate embedding for the query
        try:
            from embedding_service import EmbeddingService
            embedding_service = EmbeddingService()
            query_embedding = embedding_service.generate_embedding(query)
            
            if not query_embedding:
                return jsonify({"error": "Failed to generate query embedding"}), 500
        except Exception as e:
            logger.error(f"Error initializing embedding service: {e}")
            return jsonify({"error": "Embedding service not available. Set OPENAI_API_KEY in .env"}), 503
        
        # Get all items for this plugin with embeddings
        items = db.query(DataItem).filter(
            DataItem.plugin_name == plugin_name,
            DataItem.embedding.isnot(None)
        ).all()
        
        if not items:
            return jsonify({
                "results": [],
                "message": "No items with embeddings found. Run an import to generate embeddings."
            })
        
        # Calculate similarity scores
        scored_items = []
        for item in items:
            try:
                item_embedding = embedding_service.bytes_to_embedding(item.embedding)
                similarity = embedding_service.cosine_similarity(query_embedding, item_embedding)
                
                # Format the text for return
                text_parts = []
                if item.title:
                    text_parts.append(f"Subject: {item.title}")
                if item.item_metadata and item.item_metadata.get("from"):
                    text_parts.append(f"From: {item.item_metadata['from']}")
                if item.source_timestamp:
                    text_parts.append(f"Date: {item.source_timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
                if item.content:
                    text_parts.append(item.content)
                
                text = "\n".join(text_parts)
                
                scored_items.append({
                    "text": text,
                    "score": float(similarity),
                    "metadata": {
                        "id": item.id,
                        "title": item.title,
                        "source_id": item.source_id,
                        "item_type": item.item_type,
                        "source_timestamp": item.source_timestamp.isoformat() if item.source_timestamp else None,
                        **(item.item_metadata or {})
                    }
                })
            except Exception as e:
                logger.warning(f"Error processing item {item.id}: {e}")
                continue
        
        # Sort by similarity (descending) and take top_k
        scored_items.sort(key=lambda x: x["score"], reverse=True)
        results = scored_items[:top_k]
        
        return jsonify({
            "results": results,
            "query": query,
            "total_found": len(scored_items),
            "returned": len(results)
        })
    except Exception as e:
        logger.error(f"Error in semantic search: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/plugins/<plugin_name>/inbox", methods=["GET"])
def get_plugin_inbox(plugin_name):
    """Get all emails as flat text within a time range."""
    db = SessionLocal()
    try:
        # Get query parameters
        start_days = request.args.get("start", 180, type=int)  # Days in the past to start
        end_days = request.args.get("end", 0, type=int)  # Days in the past to end (0 = today)
        
        # Calculate date range
        now = datetime.now(timezone.utc)
        start_date = now - timedelta(days=start_days)
        end_date = now - timedelta(days=end_days)
        
        # Query data items within the date range
        items = db.query(DataItem).filter(
            DataItem.plugin_name == plugin_name,
            DataItem.source_timestamp >= start_date,
            DataItem.source_timestamp <= end_date
        ).order_by(DataItem.source_timestamp.desc()).all()
        
        # Format as flat text
        text_lines = []
        text_lines.append(f"=== Gmail Inbox: {plugin_name} ===\n")
        text_lines.append(f"Date Range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}\n")
        text_lines.append(f"Total Emails: {len(items)}\n")
        text_lines.append("=" * 80 + "\n\n")
        
        for item in items:
            # Format date
            date_str = "Unknown date"
            if item.source_timestamp:
                date_str = item.source_timestamp.strftime('%Y-%m-%d %H:%M:%S')
            elif item.created_at:
                date_str = item.created_at.strftime('%Y-%m-%d %H:%M:%S')
            
            # Get metadata
            metadata = item.item_metadata or {}
            from_addr = metadata.get('from', 'Unknown sender')
            
            # Format email
            text_lines.append(f"Date: {date_str}\n")
            text_lines.append(f"From: {from_addr}\n")
            text_lines.append(f"Subject: {item.title or 'No Subject'}\n")
            text_lines.append("-" * 80 + "\n")
            
            # Add content (limit to first 5000 chars per email to avoid huge responses)
            content = item.content or ""
            if len(content) > 5000:
                content = content[:5000] + "\n... (truncated)"
            text_lines.append(f"{content}\n")
            text_lines.append("\n" + "=" * 80 + "\n\n")
        
        # Return as plain text
        response_text = "".join(text_lines)
        return response_text, 200, {'Content-Type': 'text/plain; charset=utf-8'}
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


@app.route("/api/plugins/<plugin_name>/vector-store/sync", methods=["POST"])
def sync_plugin_to_vector_store(plugin_name):
    """Sync plugin data to OpenAI Vector Store."""
    if not vector_store_service:
        return jsonify({"error": "Vector Store service not available. Set OPENAI_API_KEY in .env"}), 503
    
    db = SessionLocal()
    try:
        # Get all data items for this plugin
        items = db.query(DataItem).filter(
            DataItem.plugin_name == plugin_name
        ).all()
        
        if not items:
            return jsonify({"error": "No data found for this plugin. Run an import first."}), 404
        
        # Format items for vector store
        data_items = []
        for item in items:
            data_items.append({
                "title": item.title,
                "content": item.content,
                "metadata": item.item_metadata or {},
                "source_timestamp": item.source_timestamp.isoformat() if item.source_timestamp else None
            })
        
        # Sync to vector store
        result = vector_store_service.sync_data_to_store(plugin_name, data_items)
        
        return jsonify({
            "success": True,
            "plugin_name": plugin_name,
            "items_synced": len(data_items),
            "vector_store_id": result.get("store_id"),
            "file_batch_id": result.get("file_batch_id"),
            "message": f"Synced {len(data_items)} items to vector store. Use the store_id in ChatGPT Custom GPT configuration."
        })
    except Exception as e:
        logger.error(f"Error syncing to vector store: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/plugins/<plugin_name>/vector-store/info", methods=["GET"])
def get_vector_store_info(plugin_name):
    """Get vector store information for a plugin."""
    if not vector_store_service:
        return jsonify({"error": "Vector Store service not available. Set OPENAI_API_KEY in .env"}), 503
    
    try:
        store_id = vector_store_service.get_store_id(plugin_name)
        if not store_id:
            return jsonify({
                "has_store": False,
                "message": "No vector store exists for this plugin. Run a sync first."
            })
        
        # Get store details from OpenAI
        vector_stores = vector_store_service._get_vector_stores_api()
        store = vector_stores.retrieve(store_id)
        
        return jsonify({
            "has_store": True,
            "store_id": store_id,
            "store_name": store.name,
            "created_at": store.created_at,
            "file_counts": store.file_counts if hasattr(store, 'file_counts') else None,
            "usage_bytes": store.usage_bytes if hasattr(store, 'usage_bytes') else None
        })
    except Exception as e:
        logger.error(f"Error getting vector store info: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


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

