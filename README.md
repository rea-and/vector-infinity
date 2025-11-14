# Vector Infinity

A personal data aggregation system that imports data from multiple sources (Gmail, TODO apps, health trackers, calendars, etc.) and provides it as context for ChatGPT Custom GPTs via REST API endpoints.

## Features

- **Plugin Architecture**: Easily extensible plugin system for adding new data sources
- **Automated Daily Imports**: Scheduled daily imports from all configured sources
- **Local Database**: All data stored locally in SQLite (lightweight, low RAM usage)
- **Custom GPT Integration**: Each plugin exposes REST API endpoints for ChatGPT Custom GPTs
- **Web UI Control Plane**: Responsive web interface for:
  - Viewing import logs
  - Manually triggering imports
  - Viewing statistics
  - API endpoint documentation
- **OpenAPI Schemas**: Each plugin includes a JSON schema ready to upload to ChatGPT Custom GPT configuration

## Requirements

- Ubuntu 25.10 (or compatible Linux distribution)
- Python 3.8+
- 1GB RAM minimum (2GB recommended for installation)
- Internet connection for API access

**Note for 1GB RAM systems**: ChromaDB requires compilation during installation which can be memory-intensive. The setup script is optimized for low RAM, but if installation fails, consider:
- Adding swap space temporarily: `sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile`
- Running installation during low system load
- Installing on a system with more RAM, then copying the `venv` directory

## Quick Start

### 1. Setup

Run the setup script on a clean Ubuntu 25.10 system:

```bash
chmod +x setup_ubuntu.sh
./setup_ubuntu.sh
```

This will:
- Install system dependencies
- Create a Python virtual environment
- Install Python packages
- Initialize the database
- Create necessary directories

### 2. Configuration

#### Environment Variables

Edit the `.env` file:

```bash
nano .env
```

**Note**: No OpenAI API key is needed for Custom GPT integration. The system uses simple SQLite text search for querying data.

The default port is 80. If you have an existing `.env` file with `WEB_PORT=5000`, update it to `WEB_PORT=80` or delete the line to use the default.

#### Plugin Configuration

Each plugin has its own configuration file in `plugins/<plugin_name>/config.json`.

**Gmail Plugins** (gmail_personal, gmail_work):
1. Enable the plugin: Set `"enabled": true` in `config.json`
2. Get Google OAuth credentials:
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project or select existing
   - Enable Gmail API
   - Create OAuth 2.0 credentials (Desktop app)
   - Download credentials as `credentials.json`
   - Place `credentials.json` in the plugin directory
3. On first run, the plugin will open a browser for authentication

**TODO App Plugin**:
1. Set `"enabled": true`
2. Configure:
   - `api_url`: Your TODO app's API endpoint
   - `api_key`: API key or token
   - `auth_type`: "bearer", "header", or "basic"

**Whoop Plugin**:
1. Set `"enabled": true`
2. Get your Whoop API key from [Whoop Developer Portal](https://developer.whoop.com/)
3. Set `api_key` in `config.json`

**Calendar Plugin**:
1. Set `"enabled": true`
2. Follow same OAuth setup as Gmail plugins
3. Enable Google Calendar API in Google Cloud Console

### 3. Running

#### Manual Run (Testing)

```bash
source venv/bin/activate
python3 app.py
```

Access the web UI at `http://localhost`

#### As a System Service

After running setup, install as a systemd service:

```bash
sudo cp /tmp/vector-infinity.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable vector-infinity
sudo systemctl start vector-infinity
```

Check status:
```bash
sudo systemctl status vector-infinity
```

View logs:
```bash
sudo journalctl -u vector-infinity -f
```

## Plugin Development

To create a new plugin:

1. Create a new directory in `plugins/`:
   ```bash
   mkdir -p plugins/my_plugin
   ```

2. Create `plugin.py`:
   ```python
   from plugin_base import DataSourcePlugin
   
   class Plugin(DataSourcePlugin):
       def __init__(self):
           super().__init__("my_plugin")
       
       def fetch_data(self):
           # Your data fetching logic
           return [
               {
                   "source_id": "unique_id",
                   "item_type": "your_type",
                   "title": "Title",
                   "content": "Content",
                   "metadata": {},
                   "source_timestamp": datetime.now()
               }
           ]
       
       def test_connection(self):
           # Test connection logic
           return True
       
       def get_config_schema(self):
           schema = super().get_config_schema()
           # Add your config fields
           return schema
   ```

3. Create `config.json`:
   ```json
   {
     "enabled": false,
     "your_config_field": "value"
   }
   ```

4. Enable the plugin by setting `"enabled": true` in `config.json`

## Custom GPT Integration

### Setting Up a Plugin in ChatGPT

1. **Get your server URL**: Make sure your Vector Infinity server is accessible (e.g., `https://your-server.com`)

2. **Edit the schema file**: Open `plugins/{plugin_name}/custom_gpt_schema.json` and replace `YOUR_SERVER_URL` with your actual server URL

3. **Create a Custom GPT**:
   - Go to [ChatGPT Custom GPTs](https://chat.openai.com/gpts)
   - Click "Create" or "Edit" on an existing GPT
   - Go to "Configure" tab
   - Scroll to "Actions" section
   - Click "Create new action"
   - Click "Import from URL" or paste the JSON schema content
   - Paste the contents of `custom_gpt_schema.json` (with your server URL)
   - Save the GPT

4. **Test it**: In a conversation with your Custom GPT, ask questions that would benefit from your data. ChatGPT will automatically call the API endpoints when needed.

Example prompts:
- "What emails did I receive about project X?"
- "Show me my upcoming calendar events"
- "What are my recent TODO items?"
- "What's my sleep data from last week?"

## API Endpoints

### Control Plane
- `GET /api/plugins` - List all plugins
- `GET /api/imports` - List import logs
- `POST /api/imports/run` - Run imports (optionally for specific plugin)
- `GET /api/stats` - Get statistics

### Plugin Context Endpoints (for Custom GPT)
- `GET /api/plugins/{plugin_name}/context` - Get context data from a plugin
  - Parameters: `limit` (default: 50), `days` (default: 30), `item_type` (optional), `query` (optional text search)
- `GET /api/plugins/{plugin_name}/search` - Search plugin data
  - Parameters: `q` (required), `limit` (default: 20), `days` (default: 30)

Example: `GET /api/plugins/gmail_personal/context?limit=20&days=7&query=meeting`

## Architecture

- **Database**: SQLite (lightweight, no separate server) for structured data
- **Backend**: Flask (lightweight web framework) with REST API endpoints
- **Scheduler**: APScheduler (background task scheduling)
- **Frontend**: Vanilla HTML/CSS/JS (responsive, mobile-friendly) - Control plane only
- **Custom GPT Integration**: Each plugin exposes endpoints that ChatGPT can call

### How It Works

1. **Import**: Plugins fetch data from various sources (Gmail, TODO apps, etc.) on a schedule
2. **Storage**: Data is stored in SQLite with metadata (title, content, timestamps, etc.)
3. **API Access**: Each plugin exposes REST endpoints:
   - `/api/plugins/{plugin_name}/context` - Get recent data as context
   - `/api/plugins/{plugin_name}/search` - Search data by text
4. **Custom GPT**: Upload the plugin's `custom_gpt_schema.json` to ChatGPT to enable the plugin
5. **ChatGPT Integration**: ChatGPT can call these endpoints to retrieve relevant context when answering questions

This allows ChatGPT to access your personal data (emails, todos, health data, calendar) as context when you're having conversations.

## Low RAM Optimization

The system is optimized for low RAM usage:
- SQLite database (no separate DB server)
- Lightweight Flask framework
- Minimal dependencies
- Efficient data storage
- Simple text search (no vector embeddings needed)

## Troubleshooting

### Plugin not loading
- Check that `plugin.py` exists and has a `Plugin` class
- Verify `config.json` has `"enabled": true`
- Check logs in `logs/` directory

### Authentication errors (Gmail/Calendar)
- Ensure `credentials.json` is in the plugin directory
- Delete `token.json` and re-authenticate
- Check OAuth scopes in Google Cloud Console

### Import failures
- Check plugin configuration
- Verify API keys/credentials
- Check network connectivity
- Review import logs in the web UI

### High memory usage
- Reduce `max_results` in plugin configs
- Reduce `days_back` in plugin configs

### Port 80 Permission Denied
If you get "Permission denied" when trying to run on port 80, the setup script should have configured this automatically. If not, run:

```bash
sudo setcap 'cap_net_bind_service=+ep' venv/bin/python3
```

This allows the Python binary to bind to port 80 without root privileges. After running this command, you can start the app normally:

```bash
source venv/bin/activate
python3 app.py
```

**Note**: If you reinstall the virtual environment or update Python, you'll need to run the `setcap` command again.

### HTTPS Setup for OAuth (Required for Gmail API)

Google requires HTTPS for OAuth redirects when using sensitive scopes like Gmail API. If you're getting "URI must use https://" errors, you need to set up HTTPS.

**Option 1: Use Nginx Reverse Proxy with Let's Encrypt (Recommended)**

1. Install Nginx and Certbot:
   ```bash
   sudo apt-get update
   sudo apt-get install -y nginx certbot python3-certbot-nginx
   ```

2. Configure Nginx to proxy to your Flask app:
   ```bash
   sudo nano /etc/nginx/sites-available/vector-infinity
   ```
   
   Add this configuration:
   ```nginx
   server {
       listen 80;
       server_name your-domain.com;  # Replace with your domain or IP
       
       location / {
           proxy_pass http://127.0.0.1:5000;  # Or whatever port your app runs on
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
   }
   ```

3. Enable the site:
   ```bash
   sudo ln -s /etc/nginx/sites-available/vector-infinity /etc/nginx/sites-enabled/
   sudo nginx -t
   sudo systemctl restart nginx
   ```

4. Get SSL certificate:
   ```bash
   sudo certbot --nginx -d your-domain.com
   ```

5. Update your `.env` file to set `WEB_PORT=5000` (or another port) since Nginx will handle port 80/443

6. Update the redirect URI in Google Cloud Console to use `https://your-domain.com/api/plugins/gmail_personal/auth/callback`

**Option 2: Use Cloudflare or Similar Service**

If you're using Cloudflare or a similar CDN/proxy service:
1. Enable SSL/TLS in Cloudflare
2. Set up a proxy rule to forward to your server
3. Make sure `X-Forwarded-Proto` header is set correctly
4. Use your Cloudflare domain in the redirect URI

**Option 3: For Testing Only - Use ngrok**

For temporary testing, you can use ngrok:
```bash
ngrok http 80
```
Then use the HTTPS URL provided by ngrok in your redirect URI.

## License

MIT License

## Support

For issues and questions, please check the logs in the `logs/` directory and the import logs in the web UI.

