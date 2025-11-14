# Vector Infinity

A personal data aggregation system that imports data from multiple sources (Gmail, WhatsApp, etc.) and provides it as context for ChatGPT Custom GPTs via REST API endpoints.

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

**Note**: For semantic search functionality, you'll need to set `OPENAI_API_KEY` in your `.env` file. This is used to generate embeddings for semantic search. See the [Semantic Search Integration](#semantic-search-integration-recommended) section for details.

The default port is 80. If you have an existing `.env` file with `WEB_PORT=5000`, update it to `WEB_PORT=80` or delete the line to use the default.

#### Plugin Configuration

Each plugin has its own configuration file in `plugins/<plugin_name>/config.json`.

**Gmail Plugin** (gmail_personal):
1. Enable the plugin: Set `"enabled": true` in `config.json`
2. Get Google OAuth credentials:
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project or select existing
   - Enable Gmail API
   - Create OAuth 2.0 credentials (Web application)
   - Download credentials as `credentials.json`
   - Place `credentials.json` in the plugin directory
3. Authenticate via the web UI using the "Authenticate" button

**WhatsApp Angel Plugin** (whatsapp_angel):
1. Enable the plugin: Set `"enabled": true` in `config.json`
2. Export your WhatsApp chat with Angel as a `.txt` file
3. Zip the `.txt` file
4. Use the "Upload & Import" button in the web UI to upload the ZIP file

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

## Semantic Search Integration (Recommended)

**For handling large amounts of context (1000+ emails), use semantic search with vector embeddings.**

Semantic search uses vector embeddings to find emails by meaning, not just keywords. This allows ChatGPT to find relevant emails even when they don't contain the exact words you're searching for.

**Example:** Searching for "vacation plans" will find emails about "trip to Italy", "holiday booking", "travel arrangements", etc.

### How It Works

1. **Import**: When you import data, embeddings are automatically generated for each email
2. **Storage**: Embeddings are stored in your local SQLite database
3. **Search**: When ChatGPT needs to search, it calls the semantic search endpoint
4. **Results**: The endpoint finds the most similar emails using cosine similarity

### Prerequisites

1. **OpenAI API Key**: Required for generating embeddings
2. **Set in `.env` file**:
   ```
   OPENAI_API_KEY=sk-your-api-key-here
   ```

### Setup Steps

#### 1. Install Dependencies

The setup script should have already installed the required packages. If not:
```bash
source venv/bin/activate
pip install openai>=1.12.0 numpy>=1.24.0
```

#### 2. Import Your Data

1. Go to the web UI: `https://your-domain.com`
2. Navigate to the "Run Imports" tab
3. Click "Run Import" for the `gmail_personal` plugin
4. Wait for the import to complete
   - **Embeddings are generated automatically during import**
   - You'll see progress: "Generating embeddings for X items..."

#### 3. Configure ChatGPT Custom GPT

1. **Download the schema**: In the Vector Infinity web UI, click "Download Schema" for your plugin
   - Or manually get: `plugins/gmail_personal/custom_gpt_schema.json`

2. **Update the server URL**: Open the schema file and replace `https://vectorinfinity.com/` with your actual server URL

3. **Add as Action in ChatGPT**:
   - Go to [ChatGPT Custom GPTs](https://chat.openai.com/gpts)
   - Create a new GPT or edit an existing one
   - Go to "Configure" tab
   - Scroll to "Actions" section
   - Click "Create new action"
   - Click "Import from URL" or paste the JSON schema content
   - Paste the contents of `custom_gpt_schema.json`
   - Add authentication if needed (API key, bearer token, etc.)
   - Save the GPT

#### 4. Use Your GPT

Now when you chat with your Custom GPT, it will automatically:
- Use the `semanticSearchGmailPersonal` action when you ask questions about emails
- Find semantically similar emails (by meaning, not just keywords)
- Include relevant context in responses

**Example queries:**
- "Find emails about my vacation" - will find emails about trips, holidays, travel, etc.
- "What did I discuss with John about the project?" - will find relevant project emails
- "Show me emails related to invoices" - will find billing, payment, receipt emails

### Benefits

- **Semantic Understanding**: Finds emails by meaning, not just exact words
- **Full Control**: Your data stays in your database
- **No Quotas**: Uses your own embeddings, not OpenAI Vector Store quotas
- **Fast**: Embeddings are pre-computed during import
- **Scalable**: Can handle thousands of emails efficiently

### Troubleshooting

#### "No items with embeddings found"

- Make sure you've run an import after setting `OPENAI_API_KEY`
- Check the import logs to see if embedding generation succeeded
- Re-run the import to generate embeddings

#### Embedding generation fails

- Check that `OPENAI_API_KEY` is set correctly in `.env`
- Verify your API key has access to the embeddings API
- Check the logs for detailed error messages

#### Search returns no results

- Make sure embeddings were generated (check import logs)
- Try a different query - semantic search works best with descriptive queries
- Check that you have emails imported for the plugin

### Technical Details

- **Embedding Model**: `text-embedding-3-small` (OpenAI)
- **Similarity Metric**: Cosine similarity
- **Storage**: Embeddings stored as BLOB in SQLite
- **Batch Processing**: Embeddings generated in batches during import for efficiency


## API Endpoints

### Control Plane
- `GET /api/plugins` - List all plugins
- `GET /api/imports` - List import logs
- `POST /api/imports/run` - Run imports (optionally for specific plugin)
- `GET /api/stats` - Get statistics

### Plugin Context Endpoints (for Custom GPT)
- `POST /api/plugins/{plugin_name}/semantic-search` - Semantic search using vector embeddings (Action)
  - Body: `{"query": "search text", "top_k": 5}`
  - Returns: Results sorted by similarity score
  - This is the recommended endpoint for Custom GPT Actions

Example: `POST /api/plugins/gmail_personal/semantic-search` with body `{"query": "vacation plans", "top_k": 5}`

## Architecture

- **Database**: SQLite (lightweight, no separate server) for structured data and vector embeddings
- **Backend**: Flask (lightweight web framework) with REST API endpoints
- **Scheduler**: APScheduler (background task scheduling)
- **Frontend**: Vanilla HTML/CSS/JS (responsive, mobile-friendly) - Control plane only
- **Embedding Service**: Generates and stores vector embeddings for semantic search
- **Custom GPT Integration**: Each plugin exposes endpoints that ChatGPT can call via Actions

### How It Works

1. **Import**: Plugins fetch data from various sources (Gmail, TODO apps, etc.) on a schedule
2. **Storage**: Data is stored in SQLite with metadata (title, content, timestamps, etc.)
3. **Embeddings**: Vector embeddings are automatically generated during import for semantic search
4. **API Access**: Each plugin exposes a semantic search endpoint:
   - `/api/plugins/{plugin_name}/semantic-search` - Semantic search using vector embeddings (Action)
5. **Custom GPT**: Upload the plugin's `custom_gpt_schema.json` to ChatGPT Actions to enable the plugin
6. **ChatGPT Integration**: ChatGPT automatically calls the semantic search endpoint when you ask questions about your data

This allows ChatGPT to access your personal data (emails, WhatsApp messages) as context when you're having conversations, using semantic search to find relevant information by meaning.

## Low RAM Optimization

The system is optimized for low RAM usage:
- SQLite database (no separate DB server)
- Lightweight Flask framework
- Minimal dependencies
- Efficient data storage
- Embeddings stored in SQLite (no separate vector database needed)
- Batch processing of embeddings during import to minimize memory usage

## Troubleshooting

### Plugin not loading
- Check that `plugin.py` exists and has a `Plugin` class
- Verify `config.json` has `"enabled": true`
- Check logs in `logs/` directory

### Authentication errors (Gmail)
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

**Google requires HTTPS for OAuth redirects when using sensitive scopes like Gmail API.**

The redirect URI you need to add to Google Cloud Console will be:
```
https://your-domain.com/api/plugins/gmail_personal/auth/callback
```

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

5. **Add redirect URI to Google Cloud Console:**
   ```
   https://your-domain.com/api/plugins/gmail_personal/auth/callback
   ```

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

