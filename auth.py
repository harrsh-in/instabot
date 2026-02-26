"""
OAuth routes for Instagram account authentication.
Handles the OAuth flow and account management with strict security.
"""

import logging
import secrets
from flask import Blueprint, request, redirect, session, jsonify, current_app, url_for
from models import db, InstagramAccount
from meta_service import MetaService, MetaAPIError
from token_store import get_store
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
auth_bp = Blueprint("auth", __name__)


def generate_state_token() -> str:
    """Generate a cryptographically secure state token for OAuth."""
    return secrets.token_urlsafe(32)


def validate_state_token(state: str) -> bool:
    """Validate the OAuth state token to prevent CSRF."""
    expected = session.pop("oauth_state", None)
    if not state or not expected:
        return False
    return secrets.compare_digest(state, expected)


@auth_bp.route("/")
def index():
    """Landing page with connection status."""
    accounts = InstagramAccount.query.all()
    token_store = get_store()
    
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Instagram Auto-Reply Service</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                   max-width: 800px; margin: 50px auto; padding: 20px; line-height: 1.6; }
            .card { background: #f5f5f5; padding: 20px; border-radius: 8px; margin: 20px 0; }
            .btn { display: inline-block; padding: 12px 24px; background: #0095f6; color: white; 
                   text-decoration: none; border-radius: 4px; margin: 5px; font-weight: 500; }
            .btn:hover { background: #0077c2; }
            .btn-danger { background: #ed4956; }
            .btn-danger:hover { background: #d9363e; }
            .status { padding: 10px; border-radius: 4px; margin: 10px 0; }
            .status.connected { background: #d4edda; color: #155724; border-left: 4px solid #28a745; }
            .status.disconnected { background: #f8d7da; color: #721c24; border-left: 4px solid #dc3545; }
            code { background: #e9ecef; padding: 2px 6px; border-radius: 3px; font-family: monospace; }
            .warning { background: #fff3cd; color: #856404; padding: 10px; border-radius: 4px; 
                      border-left: 4px solid #ffc107; margin: 10px 0; }
        </style>
    </head>
    <body>
        <h1>🤖 Instagram Auto-Reply Service</h1>
        <p>Automatically reply to comments on your Instagram posts.</p>
        
        <div class="card">
            <h2>Connection Status</h2>
    """
    
    if accounts:
        for account in accounts:
            has_token = (token_store and 
                        token_store.retrieve(account.id, account.access_token_encrypted) is not None)
            status_class = "connected" if has_token else "disconnected"
            status_text = "Connected" if has_token else "Token Not Available"
            
            html += f"""
            <div class="status {status_class}">
                <strong>@{account.instagram_username or 'Unknown'}</strong><br>
                Status: {status_text}<br>
                Page: {account.facebook_page_name or 'N/A'}<br>
                Connected: {account.created_at.strftime('%Y-%m-%d %H:%M') if account.created_at else 'Unknown'}
            </div>
            <a href="/disconnect/{account.id}" class="btn btn-danger" onclick="return confirm('Disconnect this account?')">Disconnect</a>
            <a href="/account/{account.id}/status" class="btn">View Status</a>
            <a href="/account/{account.id}/test" class="btn">Test Connection</a>
            """
    else:
        html += """
            <div class="status disconnected">
                No Instagram account connected.
            </div>
            <a href="/connect" class="btn">Connect Instagram Account</a>
        """
    
    html += """
        </div>
        
        <div class="card">
            <h2>📋 Setup Instructions</h2>
            <ol>
                <li>Click "Connect Instagram Account" above</li>
                <li>Login with Facebook (Instagram uses Facebook login)</li>
                <li>Select your Facebook Page connected to Instagram Business account</li>
                <li>Authorize the app permissions</li>
                <li>Configure webhook in Meta Developer Dashboard</li>
                <li>Test by commenting on your Instagram post!</li>
            </ol>
        </div>
        
        <div class="card">
            <h2>🔗 Important Links</h2>
            <ul>
                <li><a href="/privacy">Privacy Policy</a> (required by Meta)</li>
                <li><a href="/terms">Terms of Service</a> (required by Meta)</li>
                <li><a href="/webhook/health">Webhook Health Status</a></li>
                <li><a href="/health">Service Health</a></li>
            </ul>
        </div>
        
        <div class="card">
            <h2>⚠️ Security Notice</h2>
            <p>All access tokens are encrypted at rest using AES-256 encryption.</p>
            <p>Webhook signatures are verified on every request.</p>
        </div>
    </body>
    </html>
    """
    
    return html


@auth_bp.route("/connect")
def connect():
    """Redirect to Meta OAuth authorization."""
    meta_service: MetaService = current_app.config.get("META_SERVICE")
    
    if not meta_service:
        return """
        <h1>Configuration Error</h1>
        <p>Meta Service not configured. Check your META_APP_ID and META_APP_SECRET environment variables.</p>
        <a href="/">Go Back</a>
        """, 500
    
    # Generate a state parameter for CSRF protection
    state = generate_state_token()
    session["oauth_state"] = state
    
    auth_url = meta_service.get_oauth_url(state=state)
    return redirect(auth_url)


@auth_bp.route("/instagram/auth/callback")
def oauth_callback():
    """
    Handle OAuth callback from Meta.
    """
    meta_service: MetaService = current_app.config.get("META_SERVICE")
    token_store = get_store()
    
    # Check for errors from Meta
    error = request.args.get("error")
    error_reason = request.args.get("error_reason")
    error_description = request.args.get("error_description")
    
    if error:
        logger.error(f"OAuth error: {error} - {error_reason}: {error_description}")
        return f"""
        <h1>Authorization Failed</h1>
        <p>Error: {error}</p>
        <p>Reason: {error_reason or 'Unknown'}</p>
        <p>{error_description or ''}</p>
        <a href="/">Go Back</a>
        """, 400
    
    # Verify state parameter for CSRF protection
    state = request.args.get("state")
    if not validate_state_token(state):
        logger.warning("OAuth state mismatch - possible CSRF attack")
        return "Security check failed. Please try again.", 403
    
    # Get authorization code
    code = request.args.get("code")
    if not code:
        logger.error("No authorization code received")
        return "Authorization code missing.", 400
    
    try:
        # Exchange code for access token
        logger.info("Exchanging authorization code for access token...")
        short_token, expires_in = meta_service.exchange_code_for_token(code)
        
        # Exchange for long-lived token
        logger.info("Exchanging for long-lived token...")
        long_token, long_expires_in = meta_service.get_long_lived_token(short_token)
        
        # Get Instagram account info
        logger.info("Fetching Instagram account information...")
        account_info = meta_service.get_instagram_account_info(long_token)
        
        # Check if account already exists
        existing = InstagramAccount.query.filter_by(
            instagram_business_account_id=account_info.instagram_business_account_id
        ).first()
        
        if existing:
            # Update existing account
            existing.facebook_page_id = account_info.facebook_page_id
            existing.facebook_page_name = account_info.facebook_page_name
            existing.instagram_username = account_info.instagram_username
            existing.token_expires_at = datetime.utcnow() + timedelta(seconds=long_expires_in) if long_expires_in else None
            existing.updated_at = datetime.utcnow()
            
            if token_store:
                existing.set_access_token(long_token, token_store)
            
            account = existing
            logger.info(f"Updated existing account: @{account_info.instagram_username}")
        else:
            # Create new account
            account = InstagramAccount(
                instagram_business_account_id=account_info.instagram_business_account_id,
                instagram_username=account_info.instagram_username,
                facebook_page_id=account_info.facebook_page_id,
                facebook_page_name=account_info.facebook_page_name,
                access_token_encrypted="",  # Will be set below
                token_expires_at=datetime.utcnow() + timedelta(seconds=long_expires_in) if long_expires_in else None,
            )
            db.session.add(account)
            db.session.flush()  # Get the ID
            
            if token_store:
                account.set_access_token(long_token, token_store)
            
            logger.info(f"Created new account: @{account_info.instagram_username}")
        
        db.session.commit()
        
        # Redirect to success page with instructions
        return redirect("/")
        
    except MetaAPIError as e:
        logger.error(f"Meta API error during OAuth: {e}")
        return f"""
        <h1>Connection Failed</h1>
        <p>Error: {e}</p>
        <p>Please ensure:</p>
        <ul>
            <li>Your Instagram account is a Business or Creator account</li>
            <li>It's connected to a Facebook Page</li>
            <li>You granted all required permissions</li>
        </ul>
        <a href="/">Try Again</a>
        """, 400
        
    except Exception as e:
        logger.exception(f"Unexpected error during OAuth: {e}")
        db.session.rollback()
        return f"""
        <h1>Connection Failed</h1>
        <p>An unexpected error occurred. Please try again.</p>
        <a href="/">Go Back</a>
        """, 500


@auth_bp.route("/disconnect/<int:account_id>")
def disconnect(account_id: int):
    """Disconnect an Instagram account."""
    account = InstagramAccount.query.get_or_404(account_id)
    token_store = get_store()
    
    # Remove token from store
    if token_store:
        token_store.delete(account_id)
    
    # Delete from database
    db.session.delete(account)
    db.session.commit()
    
    logger.info(f"Disconnected account: {account.instagram_username}")
    
    return redirect("/")


@auth_bp.route("/account/<int:account_id>/status")
def account_status(account_id: int):
    """Get detailed status of an Instagram account connection."""
    account = InstagramAccount.query.get_or_404(account_id)
    meta_service: MetaService = current_app.config.get("META_SERVICE")
    token_store = get_store()
    
    token = token_store.retrieve(account_id, account.access_token_encrypted) if token_store else None
    
    # Check token validity
    token_status = "Unknown"
    token_expires = None
    
    if token and meta_service:
        try:
            expiration = meta_service.get_token_expiration(token)
            if expiration:
                token_expires = expiration.isoformat()
                token_status = "Valid" if expiration > datetime.utcnow() else "Expired"
            else:
                token_status = "Valid (no expiration)"
        except Exception as e:
            token_status = f"Error: {e}"
    else:
        token_status = "Not available"
    
    return jsonify({
        "account": account.to_dict(),
        "token_status": token_status,
        "token_expires": token_expires,
        "encryption_enabled": token_store is not None,
    })


@auth_bp.route("/account/<int:account_id>/test")
def test_connection(account_id: int):
    """Test the connection by fetching account info from Meta API."""
    account = InstagramAccount.query.get_or_404(account_id)
    meta_service: MetaService = current_app.config.get("META_SERVICE")
    token_store = get_store()
    
    token = token_store.retrieve(account_id, account.access_token_encrypted) if token_store else None
    
    if not token:
        return jsonify({
            "error": "Token not available. Please reconnect your account."
        }), 400
    
    if not meta_service:
        return jsonify({
            "error": "Meta service not configured."
        }), 500
    
    try:
        info = meta_service.get_instagram_account_info(token)
        
        return jsonify({
            "status": "success",
            "message": "Connection is working!",
            "account": {
                "instagram_username": info.instagram_username,
                "instagram_business_account_id": info.instagram_business_account_id,
                "facebook_page_name": info.facebook_page_name,
            }
        })
        
    except MetaAPIError as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "error_code": e.error_code,
        }), 400


@auth_bp.route("/accounts")
def list_accounts():
    """List all connected accounts (API endpoint)."""
    accounts = InstagramAccount.query.all()
    return jsonify({
        "accounts": [account.to_dict() for account in accounts]
    })
