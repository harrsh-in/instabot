"""
WSGI entry point for Gunicorn.

Usage:
    gunicorn -w 4 -b 0.0.0.0:8000 wsgi:application
"""

from app import create_app

# Create the WSGI application
application = create_app()

# For Gunicorn
app = application

if __name__ == "__main__":
    application.run()
