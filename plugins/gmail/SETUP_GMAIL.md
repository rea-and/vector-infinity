# Setting Up Gmail Personal Plugin

## Step 1: Create Google Cloud Project and Enable Gmail API

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click on the project dropdown at the top
3. Click "New Project"
4. Enter a project name (e.g., "Vector Infinity Gmail")
5. Click "Create"

## Step 2: Enable Gmail API

1. In your project, go to "APIs & Services" > "Library"
2. Search for "Gmail API"
3. Click on "Gmail API"
4. Click "Enable"

## Step 3: Create OAuth 2.0 Credentials

1. Go to "APIs & Services" > "Credentials"
2. Click "Create Credentials" > "OAuth client ID"
3. If prompted, configure the OAuth consent screen:
   - Choose "External" (unless you have a Google Workspace)
   - Fill in the required fields:
     - App name: "Vector Infinity"
     - User support email: Your email
     - Developer contact: Your email
   - Click "Save and Continue"
   - Add scopes: `https://www.googleapis.com/auth/gmail.readonly`
   - Click "Save and Continue"
   - **IMPORTANT:** Add test users - Click "ADD USERS" and add your Gmail address (e.g., `your-email@gmail.com`)
     - This is required because the app is in "Testing" mode
     - Only test users can authenticate until the app is published
   - Click "Save and Continue"
   - Review and go back to dashboard

4. Back in Credentials, click "Create Credentials" > "OAuth client ID"
5. **Important:** Choose "Web application" as the application type (NOT "Desktop app")
6. Give it a name (e.g., "Vector Infinity Gmail")
7. Under "Authorized redirect URIs", click "ADD URI" and add:
   - `http://your-server-ip/api/plugins/gmail/auth/callback`
   - Or if using a domain: `http://your-domain.com/api/plugins/gmail/auth/callback`
   - Replace `your-server-ip` or `your-domain.com` with your actual server IP or domain
8. Click "Create"
9. Click "Download JSON" to download the credentials file

## Step 4: Install Credentials File

1. Rename the downloaded file to `credentials.json`
2. Copy it to the plugin directory:
   ```bash
   cp ~/Downloads/credentials.json /path/to/vector-infinity/plugins/gmail/
   ```
   Or use SCP if on a remote server:
   ```bash
   scp ~/Downloads/credentials.json user@your-server:/path/to/vector-infinity/plugins/gmail/
   ```

## Step 5: Enable the Plugin

Edit the config file:
```bash
nano plugins/gmail/config.json
```

Change it to:
```json
{
  "enabled": true,
  "days_back": 7,
  "max_results": 100,
  "query": ""
}
```

## Step 6: Authenticate (First Run)

1. Make sure the application is running
2. Try to run an import manually from the web UI, or run:
   ```bash
   source venv/bin/activate
   python3 -c "from importer import DataImporter; importer = DataImporter(); importer.import_from_plugin('gmail')"
   ```

3. The first time, it will:
   - Open a browser window (or give you a URL to visit)
   - Ask you to sign in with your Gmail account
   - Ask for permission to read your emails
   - After authorization, it will save a `token.json` file in the plugin directory

## Step 7: Verify It Works

1. Go to the web UI
2. Click on "Run Imports" tab
3. Click "Run Import" for the gmail plugin
4. Check the "Import Logs" tab to see if it succeeded

## Configuration Options

In `config.json`, you can customize:

- `days_back`: How many days to look back (default: 7)
- `max_results`: Maximum number of emails to fetch (default: 100)
- `query`: Optional Gmail search query (e.g., "is:unread", "from:example@gmail.com")

## Troubleshooting

- **"credentials.json not found"**: Make sure the file is in `plugins/gmail/` directory
- **"Authentication failed"**: Delete `token.json` and try again
- **"Permission denied"**: Make sure you granted the correct permissions during OAuth
- **"Redirect URI mismatch"**: If you're getting a redirect URI mismatch error:
  1. Check the application logs to see what redirect URI is being generated
  2. Make sure the redirect URI in Google Cloud Console exactly matches what's being generated
  3. If the auto-detected URI doesn't match, you can explicitly set it by adding to your `.env` file:
     ```
     BASE_URL=https://vectorinfinity.com
     ```
     (Replace with your actual domain)
  4. Restart the application after setting BASE_URL
  5. Make sure the redirect URI in Google Cloud Console is exactly: `https://vectorinfinity.com/api/plugins/gmail/auth/callback`
- **"No browser available"**: If running on a headless server, you'll need to:
  - Use SSH port forwarding, or
  - Copy the authorization URL from the terminal and open it locally, then paste the code back

