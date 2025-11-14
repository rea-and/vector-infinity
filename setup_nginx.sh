#!/bin/bash
# Script to set up Nginx reverse proxy for Vector Infinity

set -e

if [ "$EUID" -ne 0 ]; then 
   echo "This script must be run as root (use sudo)"
   exit 1
fi

if [ -z "$1" ]; then
    echo "Usage: sudo ./setup_nginx.sh your-domain.com"
    exit 1
fi

DOMAIN=$1
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
NGINX_CONFIG="/etc/nginx/sites-available/vector-infinity"
NGINX_ENABLED="/etc/nginx/sites-enabled/vector-infinity"

echo "Setting up Nginx for $DOMAIN..."
echo ""

# Create Nginx configuration
echo "Creating Nginx configuration..."
cat > "$NGINX_CONFIG" << EOF
server {
    listen 80;
    server_name $DOMAIN;
    
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
    rm "$NGINX_ENABLED"
fi
ln -s "$NGINX_CONFIG" "$NGINX_ENABLED"

# Remove default Nginx site if it exists
if [ -L /etc/nginx/sites-enabled/default ]; then
    rm /etc/nginx/sites-enabled/default
fi

# Test Nginx configuration
nginx -t
if [ $? -eq 0 ]; then
    systemctl restart nginx
    echo "✓ Nginx configured and started"
    echo ""
    echo "Next step: Set up SSL with Let's Encrypt:"
    echo "  sudo ./setup_ssl.sh $DOMAIN"
else
    echo "⚠️  Nginx configuration test failed. Please check the configuration."
    exit 1
fi

