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

# Install system dependencies (including build tools, Nginx, and Certbot for HTTPS)
echo "Step 3: Installing system dependencies..."
sudo apt-get install -y build-essential libssl-dev libffi-dev python3-dev cmake ninja-build ufw libcap2-bin nginx certbot python3-certbot-nginx

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

# Setup Nginx reverse proxy (Required)
echo "Step 12: Setting up Nginx reverse proxy..."
NGINX_CONFIG="/etc/nginx/sites-available/vector-infinity"
NGINX_ENABLED="/etc/nginx/sites-enabled/vector-infinity"

# Ask for domain name (required)
echo ""
echo "Nginx reverse proxy setup is required for HTTPS (needed for OAuth/Gmail)."
while [ -z "$DOMAIN_NAME" ]; do
    read -p "Enter your domain name (e.g., vectorinfinity.com): " DOMAIN_NAME
    if [ -z "$DOMAIN_NAME" ]; then
        echo "⚠️  Domain name is required. Please enter a valid domain name."
    fi
done
echo ""

# Create Nginx configuration
echo "Creating Nginx configuration for $DOMAIN_NAME..."
sudo tee "$NGINX_CONFIG" > /dev/null << EOF
server {
    listen 80;
    server_name $DOMAIN_NAME;
    
    # Logging
    access_log /var/log/nginx/vector-infinity-access.log;
    error_log /var/log/nginx/vector-infinity-error.log;
    
    # Proxy to Flask app (running on port 5000)
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host;
        
        # WebSocket support (if needed in future)
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
EOF

# Enable the site
if [ -L "$NGINX_ENABLED" ]; then
    sudo rm "$NGINX_ENABLED"
fi
sudo ln -s "$NGINX_CONFIG" "$NGINX_ENABLED"

# Remove default Nginx site if it exists
if [ -L /etc/nginx/sites-enabled/default ]; then
    sudo rm /etc/nginx/sites-enabled/default
fi

# Test Nginx configuration
sudo nginx -t
if [ $? -eq 0 ]; then
    sudo systemctl restart nginx
    sudo systemctl enable nginx
    echo "✓ Nginx configured and started"
    
    # Update .env to use port 5000 (Flask app) since Nginx handles 80/443
    if [ -f ".env" ]; then
        # Update WEB_PORT to 5000 if it's 80, or add it if not present
        if grep -q "^WEB_PORT=" .env; then
            sed -i 's/^WEB_PORT=.*/WEB_PORT=5000/' .env
        else
            echo "WEB_PORT=5000" >> .env
        fi
    else
        echo "WEB_PORT=5000" > .env
    fi
    
    # Update systemd service to use port 5000
    sed -i 's/--bind 0.0.0.0:80/--bind 0.0.0.0:5000/' "$SERVICE_FILE"
    
    echo ""
    echo "Nginx is configured. Next step: Set up SSL certificate."
else
    echo "⚠️  Nginx configuration test failed. Please check the configuration manually."
    exit 1
fi

# Setup SSL certificate (Optional but recommended)
echo ""
echo "Step 13: Setting up SSL certificate (HTTPS)..."
echo ""
echo "To enable HTTPS (required for OAuth/Gmail), you need to set up an SSL certificate."
echo "Make sure your domain $DOMAIN_NAME points to this server's IP address first."
echo ""
read -p "Do you want to set up SSL certificate with Let's Encrypt now? (Y/n): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    # Check if domain resolves to this server
    echo "Checking if $DOMAIN_NAME points to this server..."
    SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || curl -s icanhazip.com 2>/dev/null || curl -s ipinfo.io/ip 2>/dev/null || echo "")
    
    if [ -z "$SERVER_IP" ]; then
        echo "⚠️  Could not determine server IP. Skipping automatic SSL setup."
        echo "You can set up SSL later with: sudo ./setup_ssl.sh $DOMAIN_NAME"
    else
        echo "Server IP: $SERVER_IP"
        
        # Use multiple DNS servers to check domain resolution (avoid localhost issues)
        DOMAIN_IP=$(dig @8.8.8.8 +short $DOMAIN_NAME 2>/dev/null | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' | head -n1 || echo "")
        
        if [ -z "$DOMAIN_IP" ]; then
            echo ""
            echo "⚠️  Warning: Could not resolve $DOMAIN_NAME to a valid IP address."
            echo ""
            echo "DNS Configuration Required:"
            echo "1. Go to your domain registrar's DNS management panel"
            echo "2. Add an A record:"
            echo "   Name: @ (or leave blank for root domain)"
            echo "   Type: A"
            echo "   Value: $SERVER_IP"
            echo "   TTL: 3600 (or default)"
            echo "3. Wait a few minutes for DNS propagation"
            echo "4. Then run: sudo ./setup_ssl.sh $DOMAIN_NAME"
            echo ""
            read -p "Continue anyway? (This will likely fail) (y/N): " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                echo "Skipping SSL setup. Configure DNS first, then run: sudo ./setup_ssl.sh $DOMAIN_NAME"
            else
                echo "Attempting SSL certificate setup (may fail if DNS is not configured)..."
                sudo certbot --nginx -d "$DOMAIN_NAME" --non-interactive --agree-tos --register-unsafely-without-email
                if [ $? -eq 0 ]; then
                    echo "✓ SSL certificate installed successfully!"
                else
                    echo "⚠️  SSL certificate installation failed. This is likely because DNS is not configured."
                    echo "   Configure DNS as shown above, then run: sudo ./setup_ssl.sh $DOMAIN_NAME"
                fi
            fi
        elif [ "$DOMAIN_IP" = "127.0.0.1" ] || [ "$DOMAIN_IP" = "127.0.1.1" ] || [ "$DOMAIN_IP" = "127.0.0.0" ]; then
            echo ""
            echo "⚠️  Warning: $DOMAIN_NAME resolves to $DOMAIN_IP (localhost)."
            echo "   This usually means DNS is not configured or there's a local hosts file entry."
            echo ""
            echo "DNS Configuration Required:"
            echo "1. Go to your domain registrar's DNS management panel"
            echo "2. Add an A record:"
            echo "   Name: @ (or leave blank for root domain)"
            echo "   Type: A"
            echo "   Value: $SERVER_IP"
            echo "   TTL: 3600 (or default)"
            echo "3. Wait a few minutes for DNS propagation"
            echo "4. Then run: sudo ./setup_ssl.sh $DOMAIN_NAME"
            echo ""
            read -p "Continue anyway? (This will likely fail) (y/N): " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                echo "Skipping SSL setup. Configure DNS first, then run: sudo ./setup_ssl.sh $DOMAIN_NAME"
            else
                echo "Attempting SSL certificate setup (may fail if DNS is not configured)..."
                sudo certbot --nginx -d "$DOMAIN_NAME" --non-interactive --agree-tos --register-unsafely-without-email
                if [ $? -eq 0 ]; then
                    echo "✓ SSL certificate installed successfully!"
                else
                    echo "⚠️  SSL certificate installation failed. This is likely because DNS is not configured."
                    echo "   Configure DNS as shown above, then run: sudo ./setup_ssl.sh $DOMAIN_NAME"
                fi
            fi
        elif [ "$DOMAIN_IP" != "$SERVER_IP" ]; then
            echo ""
            echo "⚠️  Warning: $DOMAIN_NAME resolves to $DOMAIN_IP, but this server's IP is $SERVER_IP"
            echo ""
            echo "DNS Configuration:"
            echo "1. Update your domain's A record to point to: $SERVER_IP"
            echo "2. Wait a few minutes for DNS propagation"
            echo "3. Then run: sudo ./setup_ssl.sh $DOMAIN_NAME"
            echo ""
            read -p "Continue anyway? (This will likely fail) (y/N): " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                echo "Skipping SSL setup. Update DNS first, then run: sudo ./setup_ssl.sh $DOMAIN_NAME"
            else
                echo "Attempting SSL certificate setup (may fail if DNS is not configured)..."
                sudo certbot --nginx -d "$DOMAIN_NAME" --non-interactive --agree-tos --register-unsafely-without-email
                if [ $? -eq 0 ]; then
                    echo "✓ SSL certificate installed successfully!"
                else
                    echo "⚠️  SSL certificate installation failed. This is likely because DNS is not configured correctly."
                    echo "   Update DNS as shown above, then run: sudo ./setup_ssl.sh $DOMAIN_NAME"
                fi
            fi
        else
            echo "✓ Domain DNS looks correct ($DOMAIN_NAME -> $DOMAIN_IP)"
            echo "Getting SSL certificate from Let's Encrypt..."
            sudo certbot --nginx -d "$DOMAIN_NAME" --non-interactive --agree-tos --register-unsafely-without-email
            if [ $? -eq 0 ]; then
                echo "✓ SSL certificate installed successfully!"
                echo ""
                echo "Your site is now available at: https://$DOMAIN_NAME"
            else
                echo "⚠️  SSL certificate installation failed. You can try again later with:"
                echo "   sudo ./setup_ssl.sh $DOMAIN_NAME"
            fi
        fi
    fi
else
    echo "Skipping SSL setup. You can set it up later with:"
    echo "   sudo ./setup_ssl.sh $DOMAIN_NAME"
fi

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
echo "2. To run manually (for testing):"
echo "   source venv/bin/activate"
echo "   python3 app.py"
echo "   (App runs on port 5000, Nginx proxies from port 80/443)"
echo ""
echo "3. To install as a systemd service (optional):"
echo "   sudo cp $SERVICE_FILE /etc/systemd/system/vector-infinity.service"
echo "   sudo systemctl daemon-reload"
echo "   sudo systemctl enable vector-infinity"
echo "   sudo systemctl start vector-infinity"
echo ""
echo "4. To check service status:"
echo "   sudo systemctl status vector-infinity"
echo ""
echo "The web UI will be available at:"
echo "  - HTTP: http://$DOMAIN_NAME (if SSL not set up yet)"
echo "  - HTTPS: https://$DOMAIN_NAME (if SSL certificate was installed)"
echo ""
echo "Note: The Flask app runs on port 5000, and Nginx handles ports 80/443."
echo "      This allows the app to run without root privileges."
echo ""
if ! sudo certbot certificates 2>/dev/null | grep -q "$DOMAIN_NAME" 2>/dev/null; then
    echo "⚠️  SSL certificate not yet configured. To set it up:"
    echo "   sudo ./setup_ssl.sh $DOMAIN_NAME"
    echo ""
fi
echo ""

