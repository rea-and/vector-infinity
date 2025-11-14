#!/bin/bash
# Script to set up SSL/TLS with Let's Encrypt for Vector Infinity

set -e

if [ "$EUID" -ne 0 ]; then 
   echo "This script must be run as root (use sudo)"
   exit 1
fi

if [ -z "$1" ]; then
    echo "Usage: sudo ./setup_ssl.sh your-domain.com"
    exit 1
fi

DOMAIN=$1
NGINX_CONFIG="/etc/nginx/sites-available/vector-infinity"

if [ ! -f "$NGINX_CONFIG" ]; then
    echo "Error: Nginx configuration not found at $NGINX_CONFIG"
    echo "Please run the setup script first or configure Nginx manually."
    exit 1
fi

echo "Setting up SSL for $DOMAIN..."
echo ""

# Check if domain resolves to this server
echo "Checking if $DOMAIN points to this server..."
SERVER_IP=$(curl -s ifconfig.me || curl -s icanhazip.com)
DOMAIN_IP=$(dig +short $DOMAIN | tail -n1)

if [ -z "$DOMAIN_IP" ]; then
    echo "⚠️  Warning: Could not resolve $DOMAIN. Make sure DNS is configured."
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
elif [ "$DOMAIN_IP" != "$SERVER_IP" ]; then
    echo "⚠️  Warning: $DOMAIN resolves to $DOMAIN_IP, but this server's IP is $SERVER_IP"
    echo "Make sure $DOMAIN points to this server before continuing."
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo "✓ Domain DNS looks correct"
fi

# Get SSL certificate
echo ""
echo "Getting SSL certificate from Let's Encrypt..."
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email

if [ $? -eq 0 ]; then
    echo ""
    echo "✓ SSL certificate installed successfully!"
    echo ""
    echo "Your site is now available at: https://$DOMAIN"
    echo ""
    echo "Add this redirect URI to Google Cloud Console:"
    echo "  https://$DOMAIN/api/plugins/gmail_personal/auth/callback"
    echo ""
    echo "Certificate will auto-renew. Test renewal with: sudo certbot renew --dry-run"
else
    echo "⚠️  SSL certificate installation failed. Please check the errors above."
    exit 1
fi

