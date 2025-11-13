#!/bin/bash
# Setup script for Vector Infinity on Ubuntu 25.10
# This script sets up the environment and installs all dependencies

set -e  # Exit on error

echo "========================================="
echo "Vector Infinity Setup Script"
echo "For Ubuntu 25.10"
echo "========================================="
echo ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then 
   echo "Please do not run this script as root. It will use sudo when needed."
   exit 1
fi

# Update system packages
echo "Step 1: Updating system packages..."
sudo apt-get update
sudo apt-get upgrade -y

# Install Python 3 and pip
echo "Step 2: Installing Python 3 and pip..."
sudo apt-get install -y python3 python3-pip python3-venv

# Install system dependencies (including build tools for ChromaDB)
echo "Step 3: Installing system dependencies..."
sudo apt-get install -y build-essential libssl-dev libffi-dev python3-dev cmake ninja-build ufw

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Create virtual environment
echo "Step 4: Creating Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

# Activate virtual environment
echo "Step 5: Installing Python dependencies..."
source venv/bin/activate
pip install --upgrade pip

# Install dependencies with optimizations for low RAM
# Use --only-binary to prefer pre-built wheels and avoid compilation where possible
# Install in smaller batches to reduce memory pressure
echo "Installing core dependencies first..."
pip install --only-binary :all: flask flask-cors apscheduler python-dotenv gunicorn requests python-dateutil pytz sqlalchemy

echo "Installing Google API dependencies..."
pip install --only-binary :all: google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client

echo "Installing OpenAI dependency..."
pip install --only-binary :all: openai

echo "Installing ChromaDB (this may take a while on low RAM systems)..."
# For ChromaDB, we need to allow source builds but with optimizations
# Set environment variables to reduce memory usage during compilation
export MAKEFLAGS="-j1"  # Use single job to reduce memory
export CFLAGS="-O1"     # Lower optimization to reduce memory during compile
pip install chromadb --no-cache-dir

echo "All dependencies installed successfully!"

# Create necessary directories
echo "Step 6: Creating necessary directories..."
mkdir -p data
mkdir -p logs
mkdir -p plugins

# Initialize database
echo "Step 7: Initializing database..."
python3 -c "from database import init_db; init_db(); print('Database initialized')"

# Configure firewall
echo "Step 8: Configuring firewall (UFW)..."
# Check if UFW is active, if not enable it
if ! sudo ufw status | grep -q "Status: active"; then
    echo "Enabling UFW firewall..."
    sudo ufw --force enable
fi

# Allow SSH (important to do this first to avoid locking yourself out)
if ! sudo ufw status | grep -q "22/tcp"; then
    echo "Allowing SSH (port 22)..."
    sudo ufw allow 22/tcp
fi

# Allow web server port (default 5000)
echo "Allowing web server port 5000..."
sudo ufw allow 5000/tcp comment 'Vector Infinity web UI'

# Optionally allow HTTP/HTTPS if using reverse proxy
read -p "Do you want to allow HTTP (80) and HTTPS (443) ports for reverse proxy? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    sudo ufw allow 80/tcp comment 'HTTP'
    sudo ufw allow 443/tcp comment 'HTTPS'
fi

echo "Firewall configuration complete. Current status:"
sudo ufw status numbered

# Create .env file if it doesn't exist
echo "Step 9: Setting up environment file..."
if [ ! -f ".env" ]; then
    cat > .env << EOF
# OpenAI API Configuration
OPENAI_API_KEY=your_openai_api_key_here

# Web Server Configuration
WEB_HOST=0.0.0.0
WEB_PORT=5000

# Scheduler Configuration
TZ=UTC
DAILY_IMPORT_TIME=02:00
EOF
    echo "Created .env file. Please edit it and add your OpenAI API key."
else
    echo ".env file already exists, skipping..."
fi

# Create systemd service file
echo "Step 10: Creating systemd service..."
SERVICE_FILE="/tmp/vector-infinity.service"
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Vector Infinity Data Aggregation Service
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$SCRIPT_DIR
Environment="PATH=$SCRIPT_DIR/venv/bin"
ExecStart=$SCRIPT_DIR/venv/bin/gunicorn --bind 0.0.0.0:5000 --workers 2 --threads 2 --timeout 120 app:app
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

echo ""
echo "========================================="
echo "Setup completed successfully!"
echo "========================================="
echo ""
echo "Next steps:"
echo "1. Edit .env file and add your OpenAI API key:"
echo "   nano .env"
echo ""
echo "2. Configure your plugins in the plugins/ directory:"
echo "   - Enable plugins by setting 'enabled: true' in each plugin's config.json"
echo "   - For Gmail plugins, add credentials.json files"
echo "   - For TODO app, configure API URL and key"
echo "   - For Whoop, add API key"
echo ""
echo "3. To run manually (for testing):"
echo "   source venv/bin/activate"
echo "   python3 app.py"
echo ""
echo "4. To install as a systemd service (optional):"
echo "   sudo cp $SERVICE_FILE /etc/systemd/system/vector-infinity.service"
echo "   sudo systemctl daemon-reload"
echo "   sudo systemctl enable vector-infinity"
echo "   sudo systemctl start vector-infinity"
echo ""
echo "5. To check service status:"
echo "   sudo systemctl status vector-infinity"
echo ""
echo "The web UI will be available at: http://your-server-ip:5000"
echo ""

