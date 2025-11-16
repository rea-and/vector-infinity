"""Main Flask application."""
from flask import Flask, render_template_string, redirect, url_for
from flask_cors import CORS
from flask_login import LoginManager, current_user
import logging
import config
import secrets

# Import route blueprints
from routes import plugins, imports, chat, data, export, auth
from database import User, SessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
        return db.query(User).get(int(user_id))
    except:
        return None
    finally:
        db.close()


# Make OAuth flows accessible to plugins (via services module)
from services import oauth_flows
app.oauth_flows = oauth_flows

# Register blueprints
app.register_blueprint(auth.bp)
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
