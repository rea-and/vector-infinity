"""Main Flask application."""
from flask import Flask, render_template_string
from flask_cors import CORS
import logging
import config

# Import route blueprints
from routes import plugins, imports, chat, data, export

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Make OAuth flows accessible to plugins (via services module)
from services import oauth_flows
app.oauth_flows = oauth_flows

# Register blueprints
app.register_blueprint(plugins.bp)
app.register_blueprint(imports.bp)
app.register_blueprint(chat.bp)
app.register_blueprint(data.bp)
app.register_blueprint(export.bp)


@app.route("/")
def index():
    """Serve the main UI."""
    return render_template_string(open("templates/index.html").read())


if __name__ == "__main__":
    app.run(host=config.WEB_HOST, port=config.WEB_PORT, debug=False)
