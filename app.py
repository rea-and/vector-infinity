"""Main Flask application."""
from flask import Flask, render_template_string, redirect, url_for
from flask_cors import CORS
from flask_login import LoginManager, current_user
import logging
import config
import secrets
from pathlib import Path

# Import route blueprints
from routes import plugins, imports, chat, data, export, auth, users
from database import User, SessionLocal, init_db
import sqlite3
from security import security_middleware, add_security_headers

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cache template files for performance
_template_cache = {}
def _load_template(template_name: str) -> str:
    """Load and cache template file."""
    if template_name not in _template_cache:
        template_path = Path("templates") / template_name
        if template_path.exists():
            _template_cache[template_name] = template_path.read_text(encoding='utf-8')
        else:
            logger.error(f"Template not found: {template_path}")
            return f"<html><body>Template {template_name} not found</body></html>"
    return _template_cache[template_name]


def update_database_schema():
    """Update database schema on startup if needed."""
    try:
        # Initialize database (creates tables if they don't exist)
        init_db()
        
        db_path = config.DATABASE_PATH
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            try:
                # Check if user_settings table exists and add assistant_model column if needed
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='user_settings'
                """)
                if cursor.fetchone():
                    cursor.execute("PRAGMA table_info(user_settings)")
                    columns = [row[1] for row in cursor.fetchall()]
                    if 'assistant_model' not in columns:
                        logger.info("Adding 'assistant_model' column to user_settings table...")
                        cursor.execute("""
                            ALTER TABLE user_settings 
                            ADD COLUMN assistant_model VARCHAR(50)
                        """)
                        conn.commit()
                        logger.info("✓ Successfully added 'assistant_model' column")
                
                # Check if chat_threads table exists and add chat API columns if needed
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='chat_threads'
                """)
                if cursor.fetchone():
                    cursor.execute("PRAGMA table_info(chat_threads)")
                    columns = [row[1] for row in cursor.fetchall()]
                    
                    # Make thread_id nullable (for backward compatibility)
                    # SQLite doesn't support ALTER COLUMN, so we'll just note it
                    # The column definition in the model is already nullable
                    
                    # Add previous_response_id column if needed
                    if 'previous_response_id' not in columns:
                        logger.info("Adding 'previous_response_id' column to chat_threads table...")
                        cursor.execute("""
                            ALTER TABLE chat_threads 
                            ADD COLUMN previous_response_id VARCHAR(255)
                        """)
                        conn.commit()
                        logger.info("✓ Successfully added 'previous_response_id' column")
                    
                    # Add conversation_history column if needed
                    if 'conversation_history' not in columns:
                        logger.info("Adding 'conversation_history' column to chat_threads table...")
                        cursor.execute("""
                            ALTER TABLE chat_threads 
                            ADD COLUMN conversation_history TEXT
                        """)
                        conn.commit()
                        logger.info("✓ Successfully added 'conversation_history' column")
                    
                    # Create index on previous_response_id if it doesn't exist
                    cursor.execute("""
                        SELECT name FROM sqlite_master 
                        WHERE type='index' AND name='ix_chat_threads_previous_response_id'
                    """)
                    if not cursor.fetchone():
                        try:
                            cursor.execute("""
                                CREATE INDEX ix_chat_threads_previous_response_id 
                                ON chat_threads(previous_response_id)
                            """)
                            conn.commit()
                            logger.info("✓ Successfully created index on previous_response_id")
                        except sqlite3.Error as idx_error:
                            logger.warning(f"Could not create index (may already exist): {idx_error}")
                            
            except sqlite3.Error as e:
                logger.warning(f"Database schema update check failed: {e}")
            finally:
                conn.close()
    except Exception as e:
        logger.warning(f"Database schema update check failed: {e}", exc_info=True)

app = Flask(__name__)
CORS(app, supports_credentials=True)

# Configure Flask-Login
app.secret_key = config.SECRET_KEY if hasattr(config, 'SECRET_KEY') else secrets.token_hex(32)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login_page'
login_manager.session_protection = "strong"

# Configure session cookie settings for better security and compatibility
app.config['SESSION_COOKIE_SECURE'] = False  # Set to True if using HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # Allows cookies to be sent with top-level navigations

# Custom unauthorized handler for API endpoints
@login_manager.unauthorized_handler
def unauthorized():
    """Handle unauthorized access - return JSON for API requests, redirect for HTML."""
    from flask import request, jsonify
    # If it's an API request, return JSON error instead of redirect
    if request.path.startswith('/api/'):
        return jsonify({"error": "Authentication required", "authenticated": False}), 401
    # For non-API requests, redirect to login (default behavior)
    from flask_login import current_user
    if not current_user.is_authenticated:
        return redirect(url_for('login_page'))
    return jsonify({"error": "Access denied"}), 403

# Security middleware: block automated scans and attacks
app.before_request(security_middleware)
app.after_request(add_security_headers)


@login_manager.user_loader
def load_user(user_id):
    """Load user from database."""
    db = SessionLocal()
    try:
        # Use Session.get() instead of Query.get() for SQLAlchemy 2.0 compatibility
        user = db.get(User, int(user_id))
        if user:
            logger.debug(f"Loaded user: {user.email} (ID: {user.id})")
        return user
    except Exception as e:
        logger.error(f"Error loading user {user_id}: {e}", exc_info=True)
        return None
    finally:
        db.close()


# Update database schema on startup
update_database_schema()

# Make OAuth flows accessible to plugins (via services module)
from services import oauth_flows
app.oauth_flows = oauth_flows

# Register blueprints
app.register_blueprint(auth.bp)
app.register_blueprint(users.bp)
app.register_blueprint(plugins.bp)
app.register_blueprint(imports.bp)
app.register_blueprint(chat.bp)
app.register_blueprint(data.bp)
app.register_blueprint(export.bp)


@app.route("/")
def index():
    """Serve the main UI or redirect to login."""
    if current_user.is_authenticated:
        return render_template_string(_load_template("index.html"))
    else:
        return render_template_string(_load_template("login.html"))


@app.route("/login")
def login_page():
    """Login page."""
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    return render_template_string(_load_template("login.html"))


if __name__ == "__main__":
    app.run(host=config.WEB_HOST, port=config.WEB_PORT, debug=False)
