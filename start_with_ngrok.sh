#!/bin/bash
# Launcher script that starts ngrok and the Flask app together
# This is useful for OAuth authentication which requires HTTPS

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Check if ngrok is installed
if ! command -v ngrok &> /dev/null; then
    echo "Error: ngrok is not installed."
    echo "Install it with: sudo snap install ngrok"
    echo "Or run the setup script again: ./setup_ubuntu.sh"
    exit 1
fi

# Check if ngrok is configured
if ! ngrok config check &> /dev/null; then
    echo "⚠️  ngrok is not configured yet."
    echo ""
    echo "To configure ngrok:"
    echo "1. Sign up at https://ngrok.com (free)"
    echo "2. Get your authtoken from https://dashboard.ngrok.com/get-started/your-authtoken"
    echo "3. Run: ngrok config add-authtoken YOUR_AUTHTOKEN"
    echo ""
    read -p "Do you want to configure ngrok now? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        read -p "Enter your ngrok authtoken: " authtoken
        ngrok config add-authtoken "$authtoken"
        echo "✓ ngrok configured"
    else
        echo "Exiting. Please configure ngrok first."
        exit 1
    fi
fi

# Activate virtual environment
if [ ! -d "venv" ]; then
    echo "Error: Virtual environment not found. Run setup_ubuntu.sh first."
    exit 1
fi

source venv/bin/activate

# Function to cleanup on exit
cleanup() {
    echo ""
    echo "Shutting down..."
    kill $NGROK_PID 2>/dev/null || true
    kill $FLASK_PID 2>/dev/null || true
    exit 0
}

trap cleanup SIGINT SIGTERM

# Start ngrok in background
echo "Starting ngrok..."
ngrok http 80 > /tmp/ngrok.log 2>&1 &
NGROK_PID=$!

# Wait a moment for ngrok to start
sleep 3

# Get ngrok URL
NGROK_URL=$(curl -s http://localhost:4040/api/tunnels | grep -o 'https://[^"]*\.ngrok[^"]*' | head -1)

if [ -z "$NGROK_URL" ]; then
    echo "Error: Could not get ngrok URL. Check if ngrok started correctly."
    kill $NGROK_PID 2>/dev/null || true
    exit 1
fi

echo "✓ ngrok started"
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  ngrok HTTPS URL: $NGROK_URL"
echo ""
echo "  Add this redirect URI to Google Cloud Console:"
echo "  $NGROK_URL/api/plugins/gmail_personal/auth/callback"
echo ""
echo "  Web UI: $NGROK_URL"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "Starting Flask app..."
echo "Press Ctrl+C to stop both ngrok and the app"
echo ""

# Start Flask app
python3 app.py &
FLASK_PID=$!

# Wait for both processes
wait $FLASK_PID $NGROK_PID

