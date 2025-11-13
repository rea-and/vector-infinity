# Vector Infinity

A personal data aggregation system that imports data from multiple sources (Gmail, TODO apps, health trackers, calendars, etc.) and provides it as context for LLM prompts using GPT-5.

## Features

- **Plugin Architecture**: Easily extensible plugin system for adding new data sources
- **Automated Daily Imports**: Scheduled daily imports from all configured sources
- **Local Database**: All data stored locally in SQLite (lightweight, low RAM usage)
- **Vector Database**: ChromaDB for semantic search - finds relevant context based on meaning, not just dates
- **LLM Integration**: Use imported data as context for GPT-5 prompts with semantic search
- **Web UI**: Responsive web interface for:
  - Viewing import logs
  - Manually triggering imports
  - Running LLM prompts with semantic search context
  - Viewing statistics

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

Set your OpenAI API key:
```
OPENAI_API_KEY=sk-your-key-here
```

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

Access the web UI at `http://localhost:5000`

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

## API Endpoints

- `GET /api/plugins` - List all plugins
- `GET /api/imports` - List import logs
- `POST /api/imports/run` - Run imports (optionally for specific plugin)
- `POST /api/llm/prompt` - Run LLM prompt with semantic search context
  - Body: `{"prompt": "your question", "context_limit": 10, "use_vector_search": true, "plugin_names": ["gmail_personal"]}`
- `GET /api/stats` - Get statistics

## Architecture

- **Database**: SQLite (lightweight, no separate server) for structured data
- **Vector Database**: ChromaDB (embedded, persistent) for semantic search
- **Embeddings**: OpenAI text-embedding-3-small model (efficient, cost-effective)
- **Backend**: Flask (lightweight web framework)
- **Scheduler**: APScheduler (background task scheduling)
- **LLM**: OpenAI GPT-5 API
- **Frontend**: Vanilla HTML/CSS/JS (responsive, mobile-friendly)

### How Vector Search Works

1. **Import**: When data is imported, embeddings are generated using OpenAI's embedding model
2. **Storage**: Embeddings are stored in ChromaDB alongside metadata
3. **Search**: When you ask a question, the system:
   - Generates an embedding for your question
   - Finds the most semantically similar items in the vector database
   - Retrieves those items as context for the LLM
4. **Result**: The LLM receives only the most relevant context, not just recent items

This means you can ask questions like "What did I discuss about project X?" and it will find relevant emails, todos, and calendar events even if they're from weeks ago.

## Low RAM Optimization

The system is optimized for low RAM usage:
- SQLite database (no separate DB server)
- Lightweight Flask framework
- Minimal dependencies
- Efficient data storage
- Configurable context limits for LLM prompts

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
- Lower `context_limit` for LLM prompts (default is 10 with semantic search)
- Reduce `days_back` in plugin configs
- Vector database uses persistent storage, so it won't consume RAM when not in use

### Vector database issues
- If embeddings fail, check that OpenAI API key is set correctly
- ChromaDB data is stored in `data/chroma_db/` directory
- If you need to rebuild the vector database, delete the `data/chroma_db/` directory and re-run imports

## License

MIT License

## Support

For issues and questions, please check the logs in the `logs/` directory and the import logs in the web UI.

