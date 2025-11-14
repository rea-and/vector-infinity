#!/bin/bash
# Launcher script for Vector Infinity Flask app

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Activate virtual environment
if [ ! -d "venv" ]; then
    echo "Error: Virtual environment not found. Run setup_ubuntu.sh first."
    exit 1
fi

source venv/bin/activate

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "⚠️  Warning: .env file not found. Creating from template..."
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "✓ Created .env file. Please edit it with your configuration."
    fi
fi

# Function to cleanup on exit
cleanup() {
    echo ""
    echo "Shutting down..."
    kill $FLASK_PID 2>/dev/null || true
    exit 0
}

trap cleanup SIGINT SIGTERM

# Get port from config or .env
PORT=${WEB_PORT:-5000}
if [ -f ".env" ]; then
    PORT=$(grep "^WEB_PORT=" .env 2>/dev/null | cut -d'=' -f2 || echo "5000")
fi

echo "Starting Vector Infinity..."
echo ""

# Check if running behind Nginx (port 5000) or directly (port 80)
if [ "$PORT" = "5000" ]; then
    echo "Running on port 5000 (behind Nginx reverse proxy)"
    echo "Make sure Nginx is configured and running:"
    echo "  sudo systemctl status nginx"
    echo ""
    echo "If you haven't set up Nginx yet, run:"
    echo "  sudo ./setup_nginx.sh your-domain.com"
    echo "  sudo ./setup_ssl.sh your-domain.com"
    echo ""
elif [ "$PORT" = "80" ]; then
    echo "Running directly on port 80 (HTTP only)"
    echo "⚠️  Note: OAuth (Gmail) requires HTTPS. Set up Nginx for production:"
    echo "  sudo ./setup_nginx.sh your-domain.com"
    echo "  sudo ./setup_ssl.sh your-domain.com"
    echo ""
fi

echo "Press Ctrl+C to stop"
echo ""

# Start Flask app
python3 app.py &
FLASK_PID=$!

# Wait for Flask process
wait $FLASK_PID
