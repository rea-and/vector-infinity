"""Plugin-related routes."""
from flask import Blueprint, jsonify, request, render_template_string
from flask_login import login_required, current_user
from datetime import datetime, timezone
import os
import json
import importlib.util
import secrets
import logging
from database import ImportLog, SessionLocal
import config
from services import plugin_loader, oauth_flows

logger = logging.getLogger(__name__)

bp = Blueprint('plugins', __name__, url_prefix='/api/plugins')


@bp.route("", methods=["GET"])
@login_required
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
                try:
                    with open(config_path, 'r') as f:
                        plugin_config = json.load(f)
                        enabled = plugin_config.get("enabled", False)
                except:
                    pass
            
            # Get config schema from plugin if available, otherwise empty
            if plugin:
                config_schema = plugin.get_config_schema()
            
            # Get last import time for this plugin (user-specific)
            last_import = db.query(ImportLog).filter(
                ImportLog.user_id == current_user.id,
                ImportLog.plugin_name == name,
                ImportLog.status == "success"
            ).order_by(ImportLog.completed_at.desc()).first()
            
            last_import_time = None
            last_import_records = None
            if last_import and last_import.completed_at:
                # Ensure timezone-aware datetime is converted to ISO with timezone
                dt = last_import.completed_at
                if dt.tzinfo is None:
                    # If naive datetime, assume UTC
                    from datetime import timezone
                    dt = dt.replace(tzinfo=timezone.utc)
                last_import_time = dt.isoformat()
                last_import_records = last_import.records_imported
            
            # Check authentication status and last auth time
            auth_status = None
            last_auth_time = None
            token_path = plugin_dir / "token.json"
            
            if token_path.exists():
                try:
                    # Get file modification time (when token was last saved/updated)
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


@bp.route("/<plugin_name>/auth/start", methods=["POST"])
@login_required
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


@bp.route("/<plugin_name>/auth/callback", methods=["GET"])
@login_required
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

