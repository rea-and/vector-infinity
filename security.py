"""Security middleware for blocking automated scans and attacks."""
from flask import request, abort, g
import logging
import time
from collections import defaultdict
from functools import wraps

logger = logging.getLogger(__name__)

# Common attack patterns to block
BLOCKED_PATHS = [
    '/wp-admin',
    '/wp-includes',
    '/wp-content',
    '/wp-login.php',
    '/wp-config.php',
    '/xmlrpc.php',
    '/feed/',
    '/blog/',
    '/wordpress/',
    '/wp/',
    '/administrator/',
    '/admin/',
    '/phpmyadmin/',
    '/.env',
    '/.git',
    '/.svn',
    '/.htaccess',
    '/.htpasswd',
    '/config.php',
    '/wp-load.php',
    '/license.txt',
    '/readme.html',
    '/wlwmanifest.xml',
    '/.well-known',
]

# Suspicious user agents (common bot/scanner patterns)
SUSPICIOUS_USER_AGENTS = [
    'sqlmap',
    'nikto',
    'nmap',
    'masscan',
    'zap',
    'burp',
    'w3af',
    'acunetix',
    'nessus',
    'openvas',
    'qualys',
    'masscan',
    'python-requests',
    'curl',
    'wget',
    'scanner',
    'bot',
    'crawler',
    'spider',
]

# Rate limiting: track requests per IP
_rate_limit_store = defaultdict(list)
RATE_LIMIT_WINDOW = 60  # 1 minute window
RATE_LIMIT_MAX_REQUESTS = 30  # Max requests per window for suspicious paths
RATE_LIMIT_MAX_REQUESTS_NORMAL = 100  # Max requests per window for normal paths


def is_suspicious_path(path):
    """Check if the request path matches known attack patterns."""
    path_lower = path.lower()
    return any(blocked in path_lower for blocked in BLOCKED_PATHS)


def is_suspicious_user_agent(user_agent):
    """Check if the user agent is suspicious."""
    if not user_agent:
        return True  # Missing user agent is suspicious
    
    user_agent_lower = user_agent.lower()
    return any(suspicious in user_agent_lower for suspicious in SUSPICIOUS_USER_AGENTS)


def get_client_ip():
    """Get the client IP address, handling proxies."""
    # Check for forwarded IP (from reverse proxy)
    if request.headers.get('X-Forwarded-For'):
        # X-Forwarded-For can contain multiple IPs, take the first one
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    elif request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    else:
        return request.remote_addr


def check_rate_limit(ip, path):
    """Check if IP has exceeded rate limit."""
    current_time = time.time()
    
    # Clean old entries (older than RATE_LIMIT_WINDOW seconds)
    _rate_limit_store[ip] = [
        req_time for req_time in _rate_limit_store[ip]
        if current_time - req_time < RATE_LIMIT_WINDOW
    ]
    
    # Check if suspicious path
    is_suspicious = is_suspicious_path(path)
    max_requests = RATE_LIMIT_MAX_REQUESTS if is_suspicious else RATE_LIMIT_MAX_REQUESTS_NORMAL
    
    # Check rate limit
    if len(_rate_limit_store[ip]) >= max_requests:
        logger.warning(f"Rate limit exceeded for IP {ip} on path {path} ({len(_rate_limit_store[ip])} requests in {RATE_LIMIT_WINDOW}s)")
        return False
    
    # Add current request
    _rate_limit_store[ip].append(current_time)
    return True


def security_middleware():
    """Flask before_request middleware to block attacks."""
    client_ip = get_client_ip()
    path = request.path
    user_agent = request.headers.get('User-Agent', '')
    
    # Allow legitimate API routes and static files
    # Our API routes are under /api/ and static files might be under /static/
    if path.startswith('/api/') or path.startswith('/static/'):
        # Still check rate limiting for API routes
        if not check_rate_limit(client_ip, path):
            logger.warning(f"Rate limit exceeded for {client_ip} on API path {path}")
            abort(429)  # Too Many Requests
        g.client_ip = client_ip
        return  # Allow through
    
    # Block suspicious paths immediately (but not our legitimate routes)
    if is_suspicious_path(path):
        logger.warning(f"Blocked suspicious path request from {client_ip}: {path} (User-Agent: {user_agent})")
        abort(404)  # Return 404 to not reveal it's a Flask app
    
    # Block suspicious user agents on any non-API path
    if is_suspicious_user_agent(user_agent):
        logger.warning(f"Blocked suspicious user agent from {client_ip}: {user_agent} on path {path}")
        abort(403)  # Forbidden
    
    # Check rate limiting for other paths
    if not check_rate_limit(client_ip, path):
        logger.warning(f"Rate limit exceeded for {client_ip} on path {path}")
        abort(429)  # Too Many Requests
    
    # Store IP in g for logging
    g.client_ip = client_ip


def add_security_headers(response):
    """Add security headers to all responses."""
    # Prevent clickjacking
    response.headers['X-Frame-Options'] = 'DENY'
    
    # Prevent MIME type sniffing
    response.headers['X-Content-Type-Options'] = 'nosniff'
    
    # XSS protection
    response.headers['X-XSS-Protection'] = '1; mode=block'
    
    # Referrer policy
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    
    # Content Security Policy (basic)
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline';"
    
    # Remove server header (don't reveal Flask version)
    response.headers.pop('Server', None)
    
    return response

