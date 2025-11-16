"""Plugin-related routes."""
from flask import Blueprint, jsonify, request, render_template_string
from flask_login import login_required, current_user
from datetime import datetime, timezone
import os
import json
import importlib.util
import secrets
import logging
from database import ImportLog, SessionLocal, PluginConfiguration, DataItem
from vector_store_service import VectorStoreService
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
            
            # Read nice_name from config.json if available
            nice_name = name  # Default to plugin name
            if config_path.exists():
                try:
                    with open(config_path, 'r') as f:
                        plugin_config_json = json.load(f)
                        nice_name = plugin_config_json.get("nice_name", name)
                except Exception as e:
                    logger.debug(f"Error reading config.json for {name}: {e}")
            
            # Check user-specific enabled status from database
            plugin_config_db = db.query(PluginConfiguration).filter(
                PluginConfiguration.user_id == current_user.id,
                PluginConfiguration.plugin_name == name
            ).first()
            
            # Default to False if not set in database
            enabled = False
            if plugin_config_db and plugin_config_db.config_data:
                enabled = plugin_config_db.config_data.get("enabled", False)
            
            config_schema = {}
            
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
            
            # Get total number of records for this plugin (user-specific)
            total_records = db.query(DataItem).filter(
                DataItem.user_id == current_user.id,
                DataItem.plugin_name == name
            ).count()
            
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
            
            plugin_data = {
                "name": name,
                "nice_name": nice_name,
                "enabled": enabled,
                "config_schema": config_schema,
                "last_import_time": last_import_time,
                "last_import_records": last_import_records,
                "total_records": total_records,
                "auth_status": auth_status,
                "last_auth_time": last_auth_time
            }
            
            # Add GitHub-specific configuration data from database
            if name == "github":
                plugin_config = db.query(PluginConfiguration).filter(
                    PluginConfiguration.user_id == current_user.id,
                    PluginConfiguration.plugin_name == name
                ).first()
                if plugin_config:
                    config_data = plugin_config.config_data
                    plugin_data["token_configured"] = bool(config_data.get("github_token"))
                    plugin_data["file_urls"] = config_data.get("file_urls", [])
                else:
                    plugin_data["token_configured"] = False
                    plugin_data["file_urls"] = []
            
            result.append(plugin_data)
        
        # Sort plugins: enabled first (alphabetical), then disabled (alphabetical)
        result.sort(key=lambda x: (not x["enabled"], x["name"].lower()))
        
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


@bp.route("/<plugin_name>/config", methods=["GET"])
@login_required
def get_plugin_config(plugin_name):
    """Get plugin configuration (user-specific, from database)."""
    db = SessionLocal()
    try:
        # Get user-specific configuration from database
        plugin_config = db.query(PluginConfiguration).filter(
            PluginConfiguration.user_id == current_user.id,
            PluginConfiguration.plugin_name == plugin_name
        ).first()
        
        if plugin_config:
            config_data = plugin_config.config_data.copy()
            # For GitHub plugin, don't return the token itself, just indicate if it's configured
            if plugin_name == "github" and "github_token" in config_data:
                config_data["token_configured"] = bool(config_data.get("github_token"))
                # Remove the actual token from response
                config_data.pop("github_token", None)
            return jsonify(config_data)
        else:
            # Return default/empty configuration
            if plugin_name == "github":
                return jsonify({
                    "file_urls": [],
                    "token_configured": False
                })
            return jsonify({})
    except Exception as e:
        logger.error(f"Error getting plugin config: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@bp.route("/<plugin_name>/toggle", methods=["POST"])
@login_required
def toggle_plugin(plugin_name):
    """Toggle plugin enabled/disabled status (user-specific)."""
    db = SessionLocal()
    try:
        data = request.get_json() or {}
        enabled = data.get("enabled", False)
        
        # Get or create plugin configuration
        plugin_config = db.query(PluginConfiguration).filter(
            PluginConfiguration.user_id == current_user.id,
            PluginConfiguration.plugin_name == plugin_name
        ).first()
        
        if plugin_config:
            # Update existing configuration
            current_config = plugin_config.config_data.copy() if plugin_config.config_data else {}
            current_config["enabled"] = enabled
            plugin_config.config_data = current_config
            plugin_config.updated_at = datetime.now(timezone.utc)
        else:
            # Create new configuration
            plugin_config = PluginConfiguration(
                user_id=current_user.id,
                plugin_name=plugin_name,
                config_data={"enabled": enabled}
            )
            db.add(plugin_config)
        
        try:
            db.commit()
            db.refresh(plugin_config)
        except Exception as commit_error:
            db.rollback()
            # Check if it's a unique constraint violation
            if "UNIQUE constraint failed" in str(commit_error) or "unique constraint" in str(commit_error).lower():
                # Try to get the existing config and update it
                plugin_config = db.query(PluginConfiguration).filter(
                    PluginConfiguration.user_id == current_user.id,
                    PluginConfiguration.plugin_name == plugin_name
                ).first()
                if plugin_config:
                    current_config = plugin_config.config_data.copy() if plugin_config.config_data else {}
                    current_config["enabled"] = enabled
                    plugin_config.config_data = current_config
                    plugin_config.updated_at = datetime.now(timezone.utc)
                    db.commit()
                    db.refresh(plugin_config)
                else:
                    raise commit_error
            else:
                raise commit_error
        
        logger.info(f"Toggled plugin {plugin_name} to {'enabled' if enabled else 'disabled'} for user {current_user.id}")
        
        return jsonify({
            "success": True,
            "message": f"Plugin {'enabled' if enabled else 'disabled'} successfully",
            "enabled": enabled
        })
    except Exception as e:
        db.rollback()
        logger.error(f"Error toggling plugin: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@bp.route("/<plugin_name>/config", methods=["POST"])
@login_required
def update_plugin_config(plugin_name):
    """Update plugin configuration (user-specific, stored in database)."""
    db = SessionLocal()
    try:
        data = request.get_json() or {}
        
        # Get or create plugin configuration
        plugin_config = db.query(PluginConfiguration).filter(
            PluginConfiguration.user_id == current_user.id,
            PluginConfiguration.plugin_name == plugin_name
        ).first()
        
        if plugin_config:
            # Update existing configuration
            current_config = plugin_config.config_data.copy() if plugin_config.config_data else {}
            current_config.update(data)
            plugin_config.config_data = current_config
            plugin_config.updated_at = datetime.now(timezone.utc)
        else:
            # Create new configuration
            plugin_config = PluginConfiguration(
                user_id=current_user.id,
                plugin_name=plugin_name,
                config_data=data
            )
            db.add(plugin_config)
        
        try:
            db.commit()
            db.refresh(plugin_config)
        except Exception as commit_error:
            db.rollback()
            # Check if it's a unique constraint violation
            if "UNIQUE constraint failed" in str(commit_error) or "unique constraint" in str(commit_error).lower():
                # Try to get the existing config and update it
                plugin_config = db.query(PluginConfiguration).filter(
                    PluginConfiguration.user_id == current_user.id,
                    PluginConfiguration.plugin_name == plugin_name
                ).first()
                if plugin_config:
                    current_config = plugin_config.config_data.copy()
                    current_config.update(data)
                    plugin_config.config_data = current_config
                    plugin_config.updated_at = datetime.now(timezone.utc)
                    db.commit()
                    db.refresh(plugin_config)
                else:
                    raise commit_error
            else:
                raise commit_error
        
        # Prepare response (don't include token in response)
        response_config = plugin_config.config_data.copy()
        if plugin_name == "github" and "github_token" in response_config:
            response_config["token_configured"] = bool(response_config.get("github_token"))
            response_config.pop("github_token", None)
        
        logger.info(f"Updated configuration for plugin {plugin_name} (user {current_user.id})")
        
        return jsonify({
            "success": True,
            "message": "Configuration updated successfully",
            "config": response_config
        })
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating plugin config: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


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


@bp.route("/<plugin_name>/reset", methods=["POST"])
@login_required
def reset_plugin(plugin_name):
    """Reset a specific plugin: delete all data items and import logs for this plugin (user-specific)."""
    db = SessionLocal()
    try:
        # Get confirmation from request
        data = request.get_json() or {}
        confirm = data.get("confirm", False)
        
        if not confirm:
            return jsonify({"error": "Confirmation required. Set 'confirm': true in request body."}), 400
        
        # Count items before deletion (user-specific, plugin-specific)
        items_count = db.query(DataItem).filter(
            DataItem.user_id == current_user.id,
            DataItem.plugin_name == plugin_name
        ).count()
        
        logs_count = db.query(ImportLog).filter(
            ImportLog.user_id == current_user.id,
            ImportLog.plugin_name == plugin_name
        ).count()
        
        # Delete all data items for this plugin and user
        db.query(DataItem).filter(
            DataItem.user_id == current_user.id,
            DataItem.plugin_name == plugin_name
        ).delete(synchronize_session=False)
        
        # Delete all import logs for this plugin and user
        db.query(ImportLog).filter(
            ImportLog.user_id == current_user.id,
            ImportLog.plugin_name == plugin_name
        ).delete(synchronize_session=False)
        
        db.commit()
        
        logger.info(f"Reset plugin {plugin_name} for user {current_user.id}: deleted {items_count} data items and {logs_count} import logs")
        
        # Note: Vector store cleanup would require re-uploading all remaining data
        # For now, we'll just delete from the database. The user can re-upload if needed.
        
        return jsonify({
            "success": True,
            "message": f"Successfully reset plugin {plugin_name}",
            "items_deleted": items_count,
            "logs_deleted": logs_count
        })
    except Exception as e:
        db.rollback()
        logger.error(f"Error resetting plugin {plugin_name}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()

