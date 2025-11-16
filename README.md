# Vector Infinity

A personal data aggregation system that imports data from multiple sources (Gmail, WhatsApp, WHOOP, etc.) and provides it as context via OpenAI's Assistant API with Vector Stores. Chat directly with your data through the web UI.

## Features

- **Plugin Architecture**: Easily extensible plugin system for adding new data sources
- **Automated Daily Imports**: Scheduled daily imports from all configured sources
- **Local Database**: All data stored locally in SQLite (lightweight, low RAM usage)
- **OpenAI Assistant API**: Uses OpenAI's Assistant API with Vector Stores for intelligent chat
- **Web UI Control Plane**: Responsive web interface for:
  - Viewing import logs
  - Manually triggering imports
  - Chatting with your data
  - Viewing statistics
  - Exporting data

## Requirements

- Ubuntu 25.10 (or compatible Linux distribution)
- Python 3.8+
- 1GB RAM minimum (2GB recommended for installation)
- Internet connection for API access

**Note for 1GB RAM systems**: The setup script is optimized for low RAM, but if installation fails, consider:
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

### 2. Running the Application

#### Option A: Run directly (Development)

```bash
./start.sh
```

Or manually:
```bash
source venv/bin/activate
python3 app.py
```

The web UI will be available at:
- `http://your-server-ip` if running on port 80
- `http://your-server-ip:5000` if running on port 5000 (behind Nginx)

**Note:** For OAuth authentication (Gmail), you need HTTPS. See the [HTTPS Setup](#https-setup-for-oauth-required-for-gmail-api) section below.

### 3. Configuration

#### Environment Variables

Edit the `.env` file:

```bash
nano .env
```

**Note**: You'll need to set `OPENAI_API_KEY` in your `.env` file. This is required for:
- Uploading data to OpenAI Vector Stores
- Using the Assistant API for chat functionality

```bash
OPENAI_API_KEY=sk-your-api-key-here
```

The default port is 80. If you have an existing `.env` file with `WEB_PORT=5000`, update it to `WEB_PORT=80` or delete the line to use the default.

#### Plugin Configuration

Each plugin has its own configuration file in `plugins/<plugin_name>/config.json`.

**Gmail Plugin** (gmail):
1. Enable the plugin: Set `"enabled": true` in `config.json`
2. Get Google OAuth credentials:
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project or select existing
   - Enable Gmail API
   - Create OAuth 2.0 credentials (Web application)
   - Download credentials as `credentials.json`
   - Place `credentials.json` in the plugin directory
3. Authenticate via the web UI using the "Authenticate" button

**WhatsApp Plugin** (whatsapp):
1. Enable the plugin: Set `"enabled": true` in `config.json`
2. Export your WhatsApp chat with Angel as a `.txt` file
3. Zip the `.txt` file
4. Use the "Upload & Import" button in the web UI to upload the ZIP file

**WHOOP Plugin** (whoop):
1. Enable the plugin: Set `"enabled": true` in `config.json`
2. Get WHOOP API credentials:
   - Go to [WHOOP Developer Platform](https://developer.whoop.com/)
   - Sign in with your WHOOP account (WHOOP membership required)
   - Create a new application in the Developer Dashboard
   - Note your `client_id` and `client_secret`
   - Create a `credentials.json` file in `plugins/whoop/` with:
     ```json
     {
       "client_id": "your-client-id-here",
       "client_secret": "your-client-secret-here"
     }
     ```
3. Configure redirect URI in WHOOP Developer Dashboard:
   - Add redirect URI: `https://your-domain.com/api/plugins/whoop/auth/callback`
   - **Note**: WHOOP requires HTTPS for OAuth redirects (see [HTTPS Setup](#https-setup-for-oauth-required-for-gmail-api) section)
4. Authenticate via the web UI using the "Authenticate" button
5. Configure data range (optional): Set `"days_back": 365` in `config.json` to fetch the last year of data (default: 365 days)

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

## Chat with Your Data

This application uses OpenAI's Assistant API with Vector Stores to provide intelligent chat functionality directly in the web UI.

### How It Works

1. **Import**: When you import data, it's automatically uploaded to OpenAI Vector Stores (one per plugin)
2. **Vector Stores**: OpenAI handles embeddings and vector search automatically
3. **Assistant API**: Each plugin has an Assistant that uses its Vector Store for context
4. **Chat**: Use the "Chat" tab in the web UI to ask questions about your data

### Prerequisites

1. **OpenAI API Key**: Required for Vector Stores and Assistant API
2. **Set in `.env` file**:
   ```
   OPENAI_API_KEY=sk-your-api-key-here
   ```

### Using the Chat Interface

1. **Import Your Data**:
   - Go to the "Run Imports" tab
   - Click "Run Import" for the plugin you want to use
   - Wait for the import to complete (data will be uploaded to Vector Stores)

2. **Start Chatting**:
   - Go to the "Chat" tab
   - Select the plugin you want to chat about (Gmail, WhatsApp, WHOOP)
   - Type your question and press Enter
   - The Assistant will use your imported data to answer

**Example queries:**
- "What emails did I receive about vacation plans?"
- "Show me my recovery scores from last week"
- "What did Angel and I discuss about dinner?"

### Benefits

- **Native Chat Experience**: Chat directly in the web UI, no external tools needed
- **Semantic Understanding**: OpenAI's Vector Stores provide semantic search automatically
- **No Manual Embedding Management**: OpenAI handles all embedding generation and storage
- **Scalable**: Can handle large amounts of data efficiently
- **Multi-Plugin Support**: Switch between different data sources easily


## API Endpoints

### Control Plane
- `GET /api/plugins` - List all plugins
- `GET /api/imports` - List import logs
- `POST /api/imports/run` - Run imports (optionally for specific plugin)
- `GET /api/stats` - Get statistics

### Chat Endpoints
- `POST /api/chat/threads` - Create a new chat thread
  - Returns: `{"thread_id": "thread_..."}`
- `POST /api/chat/threads/<thread_id>/messages` - Send a message
  - Body: `{"message": "your question", "plugin_name": "gmail_personal"}`
  - Returns: `{"response": "assistant response", "thread_id": "...", "assistant_id": "..."}`
- `GET /api/chat/threads/<thread_id>/messages` - Get all messages from a thread
  - Returns: `{"messages": [{"role": "user|assistant", "content": "...", "created_at": "..."}]}`

### Export Endpoints
- `GET /api/export/emails` - Export all imported emails to a text file for ChatGPT knowledge upload
- `GET /api/export/whoop` - Export all imported WHOOP health data to a text file for ChatGPT knowledge upload

## Architecture

- **Database**: SQLite (lightweight, no separate server) for structured data storage
- **Backend**: Flask (lightweight web framework) with REST API endpoints
- **Scheduler**: APScheduler (background task scheduling)
- **Frontend**: Vanilla HTML/CSS/JS (responsive, mobile-friendly) with integrated chat interface
- **Vector Stores**: OpenAI Vector Stores (one per plugin) for semantic search
- **Assistant API**: OpenAI Assistants with Vector Store integration for chat

### How It Works

1. **Import**: Plugins fetch data from various sources (Gmail, WhatsApp, WHOOP, etc.) on a schedule
2. **Storage**: Data is stored in SQLite with metadata (title, content, timestamps, etc.)
3. **Vector Store Upload**: Data is automatically uploaded to OpenAI Vector Stores during import
4. **Assistant Creation**: Each plugin gets an Assistant that uses its Vector Store for context
5. **Chat**: Users can chat directly in the web UI, and the Assistant uses Vector Store data to answer questions
6. **Export**: Export endpoints allow downloading data as text files for external use

This provides a seamless chat experience where you can ask questions about your personal data (emails, WhatsApp messages, WHOOP health data) and get intelligent answers using OpenAI's Assistant API with Vector Stores.

## Low RAM Optimization

The system is optimized for low RAM usage:
- SQLite database (no separate DB server)
- Lightweight Flask framework
- Minimal dependencies
- Efficient data storage
- Vector Stores managed by OpenAI (no local vector database needed)
- Batch processing during import to minimize memory usage

## Troubleshooting

### Plugin not loading
- Check that `plugin.py` exists and has a `Plugin` class
- Verify `config.json` has `"enabled": true`
- Check logs in `logs/` directory

### Authentication errors (Gmail/WHOOP)
- Ensure `credentials.json` is in the plugin directory with correct credentials
- Delete `token.json` and re-authenticate via the web UI
- **Gmail**: Check OAuth scopes in Google Cloud Console
- **WHOOP**: Verify redirect URI is correctly set in WHOOP Developer Dashboard
- Ensure HTTPS is properly configured (required for OAuth redirects)
- Check that the redirect URI matches exactly (including https:// and trailing path)

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

### HTTPS Setup for OAuth (Required for Gmail API and WHOOP API)

**Both Google and WHOOP require HTTPS for OAuth redirects when using their APIs.**

The redirect URIs you need to add will be:
- **Gmail**: `https://your-domain.com/api/plugins/gmail_personal/auth/callback`
- **WHOOP**: `https://your-domain.com/api/plugins/whoop/auth/callback`

**Recommended: Nginx with Let's Encrypt (Production Setup)**

The setup script will prompt you for your domain name and configure Nginx automatically. If you skipped it or want to set it up later:

1. **Set up Nginx reverse proxy:**
   ```bash
   sudo ./setup_nginx.sh your-domain.com
   ```
   This creates the Nginx configuration and enables the site.

2. **Make sure your domain points to your server:**
   - Set an A record in your DNS: `your-domain.com` → `your-server-ip`
   - Wait for DNS propagation (can take a few minutes)

3. **Get SSL certificate with Let's Encrypt:**
   ```bash
   sudo ./setup_ssl.sh your-domain.com
   ```
   This will:
   - Get a free SSL certificate from Let's Encrypt
   - Configure Nginx to use HTTPS
   - Set up automatic certificate renewal

4. **Update your `.env` file:**
   The setup script should have already set `WEB_PORT=5000`. Verify:
   ```bash
   cat .env | grep WEB_PORT
   ```
   If it shows `WEB_PORT=80`, change it to `WEB_PORT=5000` (Nginx handles 80/443)

5. **Add redirect URIs to your OAuth providers:**
   - **Google Cloud Console**: `https://your-domain.com/api/plugins/gmail_personal/auth/callback`
   - **WHOOP Developer Dashboard**: `https://your-domain.com/api/plugins/whoop/auth/callback`

6. **Restart the Flask app** (if running as a service):
   ```bash
   sudo systemctl restart vector-infinity
   ```

Your site will now be available at `https://your-domain.com` with a valid SSL certificate!

**Alternative: Use Cloudflare or Similar Service**

If you're using Cloudflare or a similar CDN/proxy service:
1. Enable SSL/TLS in Cloudflare
2. Set up a proxy rule to forward to your server
3. Make sure `X-Forwarded-Proto` header is set correctly
4. Use your Cloudflare domain in the redirect URI
5. The Flask app should still run on port 5000, Cloudflare will handle SSL termination

## License

MIT License

## Support

For issues and questions, please check the logs in the `logs/` directory and the import logs in the web UI.

