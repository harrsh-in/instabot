"""
WSGI entry point for production deployment.

This module creates the Flask application instance for WSGI servers like Gunicorn.

Usage:
    Development: python app.py
    Production:  gunicorn -w 4 -b 0.0.0.0:8000 wsgi:application

Gunicorn Configuration Recommendations:
---------------------------------------
- Workers: (2 x $num_cores) + 1 (e.g., 4 workers for 2-core machine)
- Worker Class: sync (default) or gevent for high concurrency
- Bind: 0.0.0.0:$PORT or unix:/path/to/socket
- Timeout: 30 seconds (webhooks must respond within 20 seconds)

Example Gunicorn Command:
    gunicorn \
        --workers 4 \
        --bind 0.0.0.0:8000 \
        --access-logfile - \
        --error-logfile - \
        --capture-output \
        --enable-stdio-inheritance \
        --timeout 30 \
        wsgi:application

Example Systemd Service:
    [Unit]
    Description=Flask Meta API
    After=network.target

    [Service]
    User=www-data
    Group=www-data
    WorkingDirectory=/var/www/flask-meta-api
    Environment="PATH=/var/www/flask-meta-api/.venv/bin"
    Environment="FLASK_ENV=production"
    ExecStart=/var/www/flask-meta-api/.venv/bin/gunicorn -w 4 -b 127.0.0.1:8000 wsgi:application
    Restart=always

    [Install]
    WantedBy=multi-user.target

Docker Deployment:
------------------
    FROM python:3.11-slim
    WORKDIR /app
    COPY requirements.txt .
    RUN pip install -r requirements.txt
    COPY . .
    EXPOSE 8000
    CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8000", "--timeout", "30", "wsgi:application"]

Environment Variables Required:
-------------------------------
- FLASK_SECRET_KEY: Secret key for session management (min 32 chars)
- META_APP_ID: Meta App ID from developers.facebook.com
- META_APP_SECRET: Meta App Secret from developers.facebook.com
- META_REDIRECT_URI: OAuth redirect URI (HTTPS in production)
- META_VERIFY_TOKEN: Webhook verification token (random string)
"""

import os
import sys
import logging

# Try to load .env file for development
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(env_path):
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path)
        print(f"Loaded environment from {env_path}", file=sys.stderr)
    except ImportError:
        # python-dotenv is not installed (expected in production)
        pass

# Import the application factory
from app import create_app

# Create the Flask application instance
# This 'application' variable is what WSGI servers look for
application = create_app()

# Expose as 'app' as well for some WSGI servers
app = application

# Configure logging for production
if os.environ.get("FLASK_ENV") == "production":
    gunicorn_logger = logging.getLogger("gunicorn.error")
    if gunicorn_logger.handlers:
        application.logger.handlers = gunicorn_logger.handlers
        application.logger.setLevel(gunicorn_logger.level)
    application.logger.info(
        f"Flask Meta API started in production mode. "
        f"App: {application.name}, Debug: {application.debug}"
    )
