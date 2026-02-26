"""
Flask Application Factory for Instagram Auto-Reply Service.
Production-grade configuration with strict validation.
"""

import os
import sys
import logging
from flask import Flask, jsonify
from pathlib import Path

from models import db, init_db, InstagramAccount
from meta_service import MetaService
from auth import auth_bp
from webhooks import webhook_bp
from legal import legal_bp
from token_store import init_token_store, get_store, TokenStoreError


def configure_logging(app: Flask):
    """Configure structured logging for production."""
    log_level = logging.DEBUG if app.config.get("DEBUG") else logging.INFO

    # Configure root logger with structured format
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler()],
    )

    # Reduce noise from third-party libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    app.logger.setLevel(log_level)


def validate_config(app: Flask) -> list:
    """
    Validate all required configuration.

    Returns:
        List of error messages for missing/invalid configuration
    """
    errors = []

    # Validate SECRET_KEY
    secret_key = app.config.get("SECRET_KEY", "")
    if not secret_key or secret_key == "change-me-in-production":
        errors.append("FLASK_SECRET_KEY must be set and not be the default value")
    if len(secret_key) < 32:
        errors.append("FLASK_SECRET_KEY must be at least 32 characters long")

    # Validate Meta credentials
    if not app.config.get("META_APP_ID"):
        errors.append("META_APP_ID is required")

    if not app.config.get("META_APP_SECRET"):
        errors.append("META_APP_SECRET is required")

    if not app.config.get("META_VERIFY_TOKEN"):
        errors.append("META_VERIFY_TOKEN is required")

    # Validate redirect URI is HTTPS in production
    redirect_uri = app.config.get("META_REDIRECT_URI", "")
    if app.config.get("ENV") == "production" and not redirect_uri.startswith(
        "https://"
    ):
        errors.append("META_REDIRECT_URI must use HTTPS in production")

    return errors


def create_app(config_name: str = None) -> Flask:
    """
    Application factory pattern for creating Flask app.

    Args:
        config_name: 'development', 'production', or None (auto-detect from ENV)

    Raises:
        RuntimeError: If required configuration is missing
    """
    app = Flask(__name__)

    # ==================== Configuration ====================

    # Load environment
    env = config_name or os.environ.get("FLASK_ENV", "production")
    is_production = env == "production"

    # Flask core settings
    secret_key = os.environ.get("FLASK_SECRET_KEY")
    if not secret_key:
        # Generate a random key for this session only (not persisted)
        import secrets

        secret_key = secrets.token_urlsafe(48)
        logging.warning(
            "FLASK_SECRET_KEY not set - using temporary key. Sessions will not persist!"
        )

    app.config["SECRET_KEY"] = secret_key
    app.config["DEBUG"] = not is_production
    app.config["ENV"] = env

    # Database configuration
    instance_path = Path(__file__).parent.absolute()
    db_path = instance_path / "data"
    db_path.mkdir(exist_ok=True)

    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", f"sqlite:///{db_path}/instagram_service.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
    }

    # Meta API configuration
    app.config["META_APP_ID"] = os.environ.get("META_APP_ID")
    app.config["META_APP_SECRET"] = os.environ.get("META_APP_SECRET")
    app.config["META_VERIFY_TOKEN"] = os.environ.get("META_VERIFY_TOKEN")

    # Construct redirect URI
    redirect_uri = os.environ.get("META_REDIRECT_URI")
    if not redirect_uri:
        host = os.environ.get("HOST", "localhost")
        port = os.environ.get("PORT", "5000")
        scheme = "https" if is_production else "http"
        if host == "localhost":
            redirect_uri = f"{scheme}://{host}:{port}/instagram/auth/callback"
        else:
            redirect_uri = f"{scheme}://{host}/instagram/auth/callback"

    app.config["META_REDIRECT_URI"] = redirect_uri

    # ==================== Validate Configuration ====================

    config_errors = validate_config(app)
    if config_errors:
        error_msg = "Configuration errors:\n  - " + "\n  - ".join(config_errors)
        app.logger.error(error_msg)
        # Don't raise - let the app start but log warnings
        # This allows health checks to still respond

    # ==================== Initialize Extensions ====================

    # Initialize database
    init_db(app)

    # Initialize Token Store with strict validation
    try:
        token_store = init_token_store(secret_key)
        app.config["TOKEN_STORE"] = token_store
        app.config["ENCRYPTION_ENABLED"] = True
    except TokenStoreError as e:
        app.logger.error(f"Failed to initialize token encryption: {e}")
        app.config["TOKEN_STORE"] = None
        app.config["ENCRYPTION_ENABLED"] = False
        raise RuntimeError(f"Token encryption is required: {e}")

    # Initialize Meta Service
    if app.config["META_APP_ID"] and app.config["META_APP_SECRET"]:
        app.config["META_SERVICE"] = MetaService(
            app_id=app.config["META_APP_ID"],
            app_secret=app.config["META_APP_SECRET"],
            verify_token=app.config["META_VERIFY_TOKEN"],
            redirect_uri=app.config["META_REDIRECT_URI"],
        )
        app.logger.info("MetaService initialized")
    else:
        app.logger.error("Meta API credentials not configured. OAuth will not work.")
        app.config["META_SERVICE"] = None

    # ==================== Configure Logging ====================

    configure_logging(app)

    # ==================== Register Blueprints ====================

    app.register_blueprint(auth_bp)
    app.register_blueprint(webhook_bp)
    app.register_blueprint(legal_bp)

    # ==================== Application Hooks ====================

    @app.before_request
    def load_tokens():
        """Load access tokens from database into memory cache on startup."""
        if not hasattr(app, "_tokens_loaded"):
            token_store = get_store()
            if token_store:
                accounts = InstagramAccount.query.all()
                loaded = token_store.load_from_database(accounts)
                app.logger.info(f"Loaded {loaded} access tokens from database")
            app._tokens_loaded = True

    @app.route("/health")
    def health_check():
        """Health check endpoint for monitoring."""
        # Check database connection
        try:
            from sqlalchemy import text

            db.session.execute(text("SELECT 1"))
            db_status = "connected"
        except Exception as e:
            db_status = f"error: {e}"

        # Check Meta service
        meta_status = (
            "configured" if app.config.get("META_SERVICE") else "not_configured"
        )

        # Check token store
        token_store = get_store()
        encryption_status = (
            "enabled"
            if (token_store and app.config.get("ENCRYPTION_ENABLED"))
            else "disabled"
        )

        # Overall status
        is_healthy = (
            db_status == "connected"
            and meta_status == "configured"
            and encryption_status == "enabled"
        )

        response = {
            "status": "healthy" if is_healthy else "degraded",
            "database": db_status,
            "meta_service": meta_status,
            "encryption": encryption_status,
            "environment": env,
        }

        status_code = 200 if is_healthy else 503
        return jsonify(response), status_code

    @app.route("/api/config")
    def get_config():
        """Get current configuration (safe values only)."""
        return jsonify(
            {
                "redirect_uri": app.config.get("META_REDIRECT_URI"),
                "webhook_url": f"{app.config.get('META_REDIRECT_URI', '').replace('/instagram/auth/callback', '')}/webhook/instagram",
                "environment": env,
                "encryption_enabled": app.config.get("ENCRYPTION_ENABLED", False),
            }
        )

    # ==================== Error Handlers ====================

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        app.logger.error(f"Internal server error: {error}")
        return jsonify({"error": "Internal server error"}), 500

    @app.errorhandler(403)
    def forbidden(error):
        return jsonify({"error": "Forbidden"}), 403

    # ==================== Startup Message ====================

    app.logger.info("=" * 60)
    app.logger.info("Instagram Auto-Reply Service")
    app.logger.info(f"Environment: {env}")
    app.logger.info(f"Database: {app.config['SQLALCHEMY_DATABASE_URI']}")
    app.logger.info(f"Redirect URI: {app.config['META_REDIRECT_URI']}")
    app.logger.info(
        f"Encryption: {'Enabled' if app.config.get('ENCRYPTION_ENABLED') else 'DISABLED'}"
    )
    if config_errors:
        app.logger.warning("Configuration warnings: " + ", ".join(config_errors))
    app.logger.info("=" * 60)

    return app


# Create the application instance for WSGI servers
application = create_app()

if __name__ == "__main__":
    # Development server - should not be used in production
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "127.0.0.1")  # Bind to localhost only by default
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"

    application.run(host=host, port=port, debug=debug)
