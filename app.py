"""Main Flask application."""
from flask import Flask, render_template_string, redirect, url_for
from flask_cors import CORS
from flask_login import LoginManager, current_user
import logging
import config
import secrets

# Import route blueprints
from routes import plugins, imports, chat, data, export, auth, users
from database import User, SessionLocal, init_db
import sqlite3

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate_database():
    """Run database migrations on startup."""
    try:
        # Initialize database (creates tables if they don't exist)
        init_db()
        
        # Check and add assistant_model column if needed
        db_path = config.DATABASE_PATH
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            try:
                # Check if table exists
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='user_settings'
                """)
                if cursor.fetchone():
                    # Check if column exists
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
            except sqlite3.Error as e:
                logger.warning(f"Database migration check failed: {e}")
            finally:
                conn.close()
    except Exception as e:
        logger.warning(f"Database migration check failed: {e}", exc_info=True)

app = Flask(__name__)
CORS(app, supports_credentials=True)

# Configure Flask-Login
app.secret_key = config.SECRET_KEY if hasattr(config, 'SECRET_KEY') else secrets.token_hex(32)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login_page'
login_manager.session_protection = "strong"


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


# Run database migrations on startup
migrate_database()

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
        return render_template_string(open("templates/index.html").read())
    else:
        return render_template_string(open("templates/login.html").read())


@app.route("/login")
def login_page():
    """Login page."""
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    return render_template_string(open("templates/login.html").read())


if __name__ == "__main__":
    app.run(host=config.WEB_HOST, port=config.WEB_PORT, debug=False)
