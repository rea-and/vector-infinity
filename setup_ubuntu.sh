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

# Install system dependencies (including build tools and libcap for port 80 binding)
echo "Step 3: Installing system dependencies..."
sudo apt-get install -y build-essential libssl-dev libffi-dev python3-dev cmake ninja-build ufw libcap2-bin snapd

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

# Remove old port 5000 rule if it exists
echo "Removing old port 5000 rule if present..."
sudo ufw delete allow 5000/tcp 2>/dev/null || true

# Allow web server port 80 (HTTP)
echo "Allowing web server port 80 (HTTP)..."
sudo ufw allow 80/tcp comment 'Vector Infinity web UI' 2>/dev/null || echo "Port 80 already allowed"

# Optionally allow HTTPS if using reverse proxy
read -p "Do you want to allow HTTPS (443) port for reverse proxy? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    sudo ufw allow 443/tcp comment 'HTTPS' 2>/dev/null || echo "Port 443 already allowed"
fi

echo "Firewall configuration complete. Current status:"
sudo ufw status numbered

# Create .env file if it doesn't exist
echo "Step 9: Setting up environment file..."
if [ ! -f ".env" ]; then
    cat > .env << EOF
# Web Server Configuration
WEB_HOST=0.0.0.0
WEB_PORT=80

# Scheduler Configuration
TZ=UTC
DAILY_IMPORT_TIME=02:00
EOF
    echo "Created .env file."
else
    echo ".env file already exists, skipping..."
fi

# Allow Python to bind to port 80 without root (using setcap)
echo "Step 10: Configuring port 80 binding permissions..."
PYTHON_BIN="$SCRIPT_DIR/venv/bin/python3"
if [ -f "$PYTHON_BIN" ] || [ -L "$PYTHON_BIN" ]; then
    # Resolve symlink to actual file (setcap requires regular file, not symlink)
    if [ -L "$PYTHON_BIN" ]; then
        PYTHON_BIN=$(readlink -f "$PYTHON_BIN")
        echo "Resolved Python symlink to: $PYTHON_BIN"
    fi
    
    # Find setcap command (usually in /usr/sbin or /sbin)
    SETCAP_CMD=""
    for path in /usr/sbin/setcap /sbin/setcap $(which setcap 2>/dev/null); do
        if [ -f "$path" ] && [ -x "$path" ]; then
            SETCAP_CMD="$path"
            break
        fi
    done
    
    if [ -n "$SETCAP_CMD" ] && [ -f "$PYTHON_BIN" ]; then
        echo "Setting capabilities on: $PYTHON_BIN"
        sudo "$SETCAP_CMD" 'cap_net_bind_service=+ep' "$PYTHON_BIN"
        if [ $? -eq 0 ]; then
            echo "✓ Python binary can now bind to port 80 without root privileges"
            # Verify it worked
            if command -v getcap >/dev/null 2>&1; then
                getcap "$PYTHON_BIN" 2>/dev/null || true
            fi
        else
            echo "⚠ Warning: Failed to set capabilities. You may need to run manually:"
            echo "   sudo setcap 'cap_net_bind_service=+ep' $PYTHON_BIN"
        fi
    else
        if [ -z "$SETCAP_CMD" ]; then
            echo "⚠ Warning: setcap command not found. Install libcap2-bin:"
            echo "   sudo apt-get install -y libcap2-bin"
        fi
        if [ ! -f "$PYTHON_BIN" ]; then
            echo "⚠ Warning: Python binary not found at: $PYTHON_BIN"
        fi
        echo "   Then run: sudo setcap 'cap_net_bind_service=+ep' $PYTHON_BIN"
    fi
else
    echo "⚠ Warning: Could not find Python binary to set capabilities"
fi

# Create systemd service file
echo "Step 11: Creating systemd service..."
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
ExecStart=$SCRIPT_DIR/venv/bin/gunicorn --bind 0.0.0.0:80 --workers 2 --threads 2 --timeout 120 app:app
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
echo "1. Configure your plugins in the plugins/ directory:"
echo "   - Enable plugins by setting 'enabled: true' in each plugin's config.json"
echo "   - For Gmail plugins, add credentials.json files"
echo "   - For TODO app, configure API URL and key"
echo "   - For Whoop, add API key"
echo ""
echo "3. To run manually (for testing):"
echo "   source venv/bin/activate"
echo "   python3 app.py"
echo "   (Port 80 binding is configured via setcap, no sudo needed)"
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
echo "The web UI will be available at: http://your-server-ip"
echo ""
echo "Note: Port 80 binding is configured using setcap, so you can run"
echo "      the app without root privileges. The systemd service runs as"
echo "      your user account (not root) for better security."
echo ""
echo "Step 12: Installing ngrok (for HTTPS OAuth testing)..."
if ! command -v ngrok &> /dev/null; then
    sudo snap install ngrok
    echo "✓ ngrok installed"
    echo ""
    echo "⚠️  IMPORTANT: To use ngrok for OAuth:"
    echo "   1. Sign up at https://ngrok.com (free)"
    echo "   2. Get your authtoken from https://dashboard.ngrok.com/get-started/your-authtoken"
    echo "   3. Run: ngrok config add-authtoken YOUR_AUTHTOKEN"
    echo "   4. Use the launcher script: ./start_with_ngrok.sh"
else
    echo "✓ ngrok already installed"
fi
echo ""

