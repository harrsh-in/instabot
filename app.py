"""
Meta (Facebook/Instagram) OAuth Integration Flask Application

This module provides OAuth 2.0 authentication flow for Instagram Business Accounts,
with production-grade security features including CSRF protection via state parameter,
secure cookie settings, and PKCE support.

It also includes webhook handling for Instagram comment events.

Routes:
    OAuth:
        GET  /auth/meta      - Initiate OAuth flow
        GET  /auth/callback  - OAuth callback handler
        GET  /auth/status    - Check authentication status
        POST /auth/logout    - Logout and clear credentials

    Webhooks:
        GET  /instagram/webhook - Meta webhook verification
        POST /instagram/webhook - Receive webhook events

    Health:
        GET  /health         - Health check endpoint

Environment Variables:
    Required:
        FLASK_SECRET_KEY    - Secret key for session management
        META_APP_ID         - Meta App ID
        META_APP_SECRET     - Meta App Secret
        META_REDIRECT_URI   - OAuth redirect URI
        META_VERIFY_TOKEN   - Webhook verification token
"""

import os
import secrets
import logging
import hashlib
import base64
import hmac
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

import requests
from flask import Flask, request, redirect, jsonify, session, Response, Blueprint
from werkzeug.exceptions import BadRequest

# Configure logging - Docker-friendly (stdout by default, file if writable)
def setup_logging():
    """Setup logging with fallback to console only if file access fails."""
    # Console handler (always works)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    
    # Root logger
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    logger.addHandler(console_handler)
    
    # Comment logger
    comment_logger = logging.getLogger("comments")
    comment_logger.setLevel(logging.INFO)
    comment_logger.propagate = False
    
    # Try to add file handlers (may fail in Docker if no write permission)
    try:
        os.makedirs("logs", exist_ok=True)
        
        # Test if we can write to logs directory
        test_file = os.path.join("logs", ".write_test")
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        
        # File handler for all logs
        file_handler = logging.FileHandler("logs/app.log")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        logger.addHandler(file_handler)
        
        # File handler for comments
        comment_file_handler = logging.FileHandler("logs/comments.log")
        comment_file_handler.setLevel(logging.INFO)
        comment_file_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
        comment_logger.addHandler(comment_file_handler)
        
        logger.info("File logging enabled")
    except (PermissionError, OSError) as e:
        # In Docker or restricted environments, use console only
        comment_logger.addHandler(console_handler)
        logger.info(f"File logging disabled (using console only): {e}")
    
    return logger, comment_logger


# Setup logging on module load
logger, comment_logger = setup_logging()

# ============================================================================
# In-Memory Storage
# ============================================================================

# Import database module
from db import (
    init_app as init_db_app,
    save_account,
    load_account,
    clear_account,
    update_token,
)
from legal import legal_bp

# In-memory cache of account (loaded from DB on startup)
account_store: Dict[str, Any] = {
    "access_token": None,
    "token_expires_at": None,
    "token_type": None,
    "days_remaining": None,
    "instagram_business_id": None,
    "page_id": None,
    "user_name": None,
    "account_type": None,  # 'BUSINESS' or 'CREATOR'
    "business_manager_id": None,
    "business_manager_name": None,
    "connected_at": None,
}

# Store recent webhook payloads for debugging (max 10)
recent_webhooks: list = []


def reload_account_from_db():
    """Load account from database into memory cache."""
    global account_store
    db_account = load_account()
    if db_account:
        account_store.update(db_account)
        logger.info(
            f"Loaded account from database: {db_account.get('user_name') or db_account.get('instagram_business_id')}"
        )
    else:
        logger.info("No existing account found in database")


# CSRF state storage with expiry
state_store: Dict[str, Dict[str, Any]] = {}
STATE_EXPIRY_MINUTES = 10

# ============================================================================
# Configuration
# ============================================================================


class Config:
    """Configuration container."""

    META_APP_ID: str = ""
    META_APP_SECRET: str = ""
    META_REDIRECT_URI: str = ""
    META_VERIFY_TOKEN: str = ""
    META_API_VERSION: str = "v18.0"
    SECRET_KEY: str = ""
    STATE_EXPIRY_SECONDS: int = 600


# Required OAuth scopes for Instagram Business Account
REQUIRED_SCOPES = [
    "business_management",
    "instagram_basic",
    "instagram_content_publish",
    "instagram_manage_comments",
    "instagram_manage_messages",
    "pages_read_engagement",
    "pages_show_list",
    "public_profile",
]

# ============================================================================
# Utility Functions
# ============================================================================


def generate_pkce_pair() -> tuple[str, str]:
    """Generate PKCE code verifier and challenge."""
    code_verifier = (
        base64.urlsafe_b64encode(secrets.token_bytes(64)).decode("utf-8").rstrip("=")
    )

    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("utf-8")).digest())
        .decode("utf-8")
        .rstrip("=")
    )

    return code_verifier, code_challenge


def generate_state() -> str:
    """Generate a cryptographically secure random state parameter."""
    return secrets.token_urlsafe(32)


def store_state(state: str, code_verifier: Optional[str] = None) -> None:
    """Store state with expiry for CSRF protection."""
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=STATE_EXPIRY_MINUTES)
    state_store[state] = {"expires_at": expires_at, "code_verifier": code_verifier}
    logger.debug(f"Stored state: {state[:16]}... (expires: {expires_at})")


def validate_and_consume_state(state: str) -> tuple[bool, Optional[str]]:
    """Validate state parameter and return associated code verifier if valid."""
    if not state:
        return False, None

    stored = state_store.pop(state, None)
    if not stored:
        logger.warning("State not found or already consumed")
        return False, None

    if datetime.now(timezone.utc) > stored["expires_at"]:
        logger.warning("State has expired")
        return False, None

    return True, stored.get("code_verifier")


def cleanup_expired_states() -> None:
    """Remove expired states from the store."""
    now = datetime.now(timezone.utc)
    expired = [s for s, data in state_store.items() if now > data["expires_at"]]
    for state in expired:
        del state_store[state]
    if expired:
        logger.debug(f"Cleaned up {len(expired)} expired states")


def get_error_redirect(error_message: str, include_error: bool = True) -> Response:
    """Create redirect response for errors."""
    safe_error = error_message.replace("\n", " ").replace("\r", "")[:200]
    logger.error(f"OAuth error: {safe_error}")

    if include_error:
        return redirect(f"/instagram/auth/status?error=auth_failed")
    return redirect("/instagram/auth/status")


def exchange_code_for_token(
    code: str, code_verifier: Optional[str] = None
) -> tuple[Optional[str], Optional[int], Optional[str]]:
    """Exchange authorization code for access token."""
    token_url = (
        f"https://graph.facebook.com/{Config.META_API_VERSION}/oauth/access_token"
    )

    params = {
        "client_id": Config.META_APP_ID,
        "client_secret": Config.META_APP_SECRET,
        "redirect_uri": Config.META_REDIRECT_URI,
        "code": code,
    }

    if code_verifier:
        params["code_verifier"] = code_verifier

    try:
        response = requests.get(token_url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        if "error" in data:
            error_msg = data["error"].get("message", "Unknown error")
            logger.error(f"Token exchange failed: {error_msg}")
            return None, None, f"Token exchange failed: {error_msg}"

        access_token = data.get("access_token")
        expires_in = data.get("expires_in")

        if not access_token:
            return None, None, "No access token in response"

        return access_token, expires_in, None

    except requests.Timeout:
        logger.error("Token exchange request timed out")
        return None, None, "Request timed out"
    except requests.RequestException as e:
        logger.error(f"Token exchange request failed: {e}")
        return None, None, "Network error during token exchange"


def exchange_for_long_lived_token(
    short_lived_token: str,
) -> tuple[Optional[str], Optional[int], Optional[str]]:
    """
    Exchange short-lived token for long-lived token (60 days validity).

    Meta's token expiry:
    - Short-lived tokens: 1 hour
    - Long-lived tokens: 60 days

    Args:
        short_lived_token: The short-lived access token from OAuth

    Returns:
        Tuple of (long_lived_token, expires_in_seconds, error_message)
    """
    exchange_url = (
        f"https://graph.facebook.com/{Config.META_API_VERSION}/oauth/access_token"
    )

    params = {
        "grant_type": "fb_exchange_token",
        "client_id": Config.META_APP_ID,
        "client_secret": Config.META_APP_SECRET,
        "fb_exchange_token": short_lived_token,
    }

    try:
        logger.info("Exchanging short-lived token for long-lived token...")
        response = requests.get(exchange_url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        if "error" in data:
            error_msg = data["error"].get("message", "Unknown error")
            logger.error(f"Token exchange failed: {error_msg}")
            # Fall back to short-lived token
            return None, None, f"Long-lived token exchange failed: {error_msg}"

        long_lived_token = data.get("access_token")
        expires_in = data.get("expires_in")

        if not long_lived_token:
            return None, None, "No long-lived token in response"

        # Meta long-lived tokens are typically 60 days (5184000 seconds)
        # If expires_in not returned, default to 60 days
        if not expires_in:
            expires_in = 5184000  # 60 days in seconds
            logger.info(
                "expires_in not provided, assuming 60 days for long-lived token"
            )

        # Calculate days for logging
        days_valid = round(expires_in / 86400, 1)
        logger.info(
            f"Successfully obtained long-lived token (valid for ~{days_valid} days)"
        )

        return long_lived_token, expires_in, None

    except requests.Timeout:
        logger.error("Long-lived token exchange timed out")
        return None, None, "Request timed out"
    except requests.RequestException as e:
        logger.error(f"Long-lived token exchange failed: {e}")
        return None, None, "Network error during token exchange"


def fetch_instagram_accounts_directly(
    access_token: str,
) -> tuple[Optional[dict], Optional[str]]:
    """
    Fetch Instagram Business/Creator accounts directly (not via Facebook Pages).
    This works for Instagram Creator accounts and some Business accounts.
    """
    graph_url = f"https://graph.facebook.com/{Config.META_API_VERSION}"

    try:
        # Get user's Instagram accounts directly
        # This endpoint returns both Business and Creator accounts
        ig_url = f"{graph_url}/me/instagram_accounts"
        params = {
            "access_token": access_token,
            "fields": "id,username,name,account_type",
        }

        response = requests.get(ig_url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        if "error" in data:
            error_msg = data["error"].get("message", "Unknown error")
            logger.warning(f"Direct Instagram fetch failed: {error_msg}")
            return None, error_msg

        accounts = data.get("data", [])
        if not accounts:
            logger.warning("No Instagram accounts found via direct fetch")
            return None, "No Instagram accounts found"

        # Use the first Instagram account
        ig_account = accounts[0]
        ig_business_id = ig_account.get("id")
        ig_username = ig_account.get("username")
        ig_name = ig_account.get("name")
        account_type = ig_account.get("account_type", "unknown")

        logger.info(
            f"Found Instagram {account_type} account: @{ig_username} (ID: {ig_business_id})"
        )

        return {
            "instagram_business_id": ig_business_id,
            "page_id": None,  # No Facebook page for direct-connected accounts
            "page_name": None,
            "instagram_username": ig_username,
            "instagram_name": ig_name,
            "account_type": account_type,  # 'BUSINESS' or 'CREATOR'
        }, None

    except requests.Timeout:
        logger.error("Direct Instagram fetch timed out")
        return None, "Request timed out"
    except requests.RequestException as e:
        logger.error(f"Direct Instagram fetch failed: {e}")
        return None, "Network error fetching Instagram account"


def fetch_instagram_business_account(
    access_token: str,
) -> tuple[Optional[dict], Optional[str]]:
    """
    Fetch Instagram Business/Creator Account using access token.

    Tries multiple methods:
    1. Via Facebook Pages (for Business accounts connected to Pages)
    2. Direct Instagram accounts fetch (for Creator accounts and some Business accounts)
    """
    graph_url = f"https://graph.facebook.com/{Config.META_API_VERSION}"

    # Method 1: Try via Facebook Pages (most common for Business accounts)
    try:
        logger.info("Trying to fetch Instagram account via Facebook Pages...")
        pages_url = f"{graph_url}/me/accounts"
        pages_params = {
            "access_token": access_token,
            "fields": "id,name,instagram_business_account",
        }

        pages_response = requests.get(pages_url, params=pages_params, timeout=30)
        pages_response.raise_for_status()
        pages_data = pages_response.json()

        if "error" not in pages_data:
            pages = pages_data.get("data", [])

            if pages:
                # Find page with Instagram Business Account
                for page in pages:
                    ig_account = page.get("instagram_business_account")
                    if ig_account:
                        ig_business_id = ig_account.get("id")
                        page_id = page.get("id")
                        page_name = page.get("name")

                        # The Instagram username might already be in the page response
                        # If not, we'll try to fetch it, but if that fails, use the ID
                        ig_username = ig_account.get("username")
                        ig_name = ig_account.get("name")

                        # Try to fetch extra details, but don't fail if we can't
                        try:
                            ig_url = f"{graph_url}/{ig_business_id}"
                            ig_params = {
                                "access_token": access_token,
                                "fields": "id,username,name,account_type",
                            }
                            ig_response = requests.get(
                                ig_url, params=ig_params, timeout=10
                            )
                            ig_data = ig_response.json()

                            if "error" not in ig_data:
                                ig_username = ig_data.get("username") or ig_username
                                ig_name = ig_data.get("name") or ig_name
                                account_type = ig_data.get("account_type", "BUSINESS")
                            else:
                                logger.warning(
                                    f"Could not fetch IG details: {ig_data['error']}"
                                )
                                account_type = "BUSINESS"  # Assume business
                        except Exception as e:
                            logger.warning(f"Could not fetch IG details: {e}")
                            account_type = "BUSINESS"

                        logger.info(
                            f"✓ Found Instagram account via Facebook Page: {page_name}"
                        )
                        return {
                            "instagram_business_id": ig_business_id,
                            "page_id": page_id,
                            "page_name": page_name,
                            "instagram_username": ig_username
                            or f"user_{ig_business_id[-8:]}",
                            "instagram_name": ig_name,
                            "account_type": (
                                account_type if "account_type" in dir() else "BUSINESS"
                            ),
                        }, None

                logger.warning(
                    "Facebook Pages found but none have connected Instagram Business accounts"
                )
            else:
                logger.info("No Facebook Pages found, trying direct Instagram fetch...")
        else:
            logger.warning(f"Pages fetch returned error: {pages_data['error']}")

    except requests.Timeout:
        logger.error("Facebook Pages fetch timed out")
    except requests.RequestException as e:
        logger.error(f"Facebook Pages fetch failed: {e}")

    # Method 2: Try direct Instagram accounts fetch (for Creator accounts)
    logger.info("Trying to fetch Instagram account directly...")
    direct_result, direct_error = fetch_instagram_accounts_directly(access_token)

    if direct_result:
        return direct_result, None

    # Method 3: Try to get Instagram account via /me endpoint with fields
    try:
        logger.info("Trying to fetch Instagram account via /me endpoint...")
        me_url = f"{graph_url}/me"
        params = {
            "access_token": access_token,
            "fields": "id,name,instagram_accounts{username,name,id,account_type}",
        }

        response = requests.get(me_url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        if "error" not in data:
            ig_accounts = data.get("instagram_accounts", {}).get("data", [])
            if ig_accounts:
                ig_account = ig_accounts[0]
                logger.info(
                    f"Found Instagram account via /me: @{ig_account.get('username')}"
                )
                return {
                    "instagram_business_id": ig_account.get("id"),
                    "page_id": None,
                    "page_name": None,
                    "instagram_username": ig_account.get("username"),
                    "instagram_name": ig_account.get("name"),
                    "account_type": ig_account.get("account_type", "unknown"),
                }, None
    except Exception as e:
        logger.warning(f"/me endpoint fetch failed: {e}")

    # Method 4: Try to get Instagram account via user's Business Manager assignment
    # Try multiple approaches to find the Instagram account
    try:
        logger.info(
            "Trying to find Instagram account via Business Manager assignments..."
        )

        # Approach 1: Get user's assigned Instagram business accounts
        try:
            logger.info("  Trying /me/assigned_instagram_accounts...")
            assigned_url = f"{graph_url}/me/assigned_instagram_accounts"
            params = {
                "access_token": access_token,
                "fields": "id,username,name,account_type",
            }

            response = requests.get(assigned_url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if "error" not in data:
                accounts = data.get("data", [])
                if accounts:
                    ig_account = accounts[0]
                    logger.info(
                        f"✓ Found via /assigned_instagram_accounts: @{ig_account.get('username')}"
                    )
                    return {
                        "instagram_business_id": ig_account.get("id"),
                        "page_id": None,
                        "page_name": None,
                        "instagram_username": ig_account.get("username"),
                        "instagram_name": ig_account.get("name"),
                        "account_type": ig_account.get("account_type", "BUSINESS"),
                    }, None
        except requests.HTTPError as e:
            try:
                err = e.response.json().get("error", {}).get("message", str(e))
                logger.warning(f"  /assigned_instagram_accounts failed: {err}")
            except:
                logger.warning(f"  /assigned_instagram_accounts failed: {e}")

        # Approach 2: Get Business Manager info and then assets
        try:
            logger.info("  Fetching Business Manager info...")
            bm_url = f"{graph_url}/me/businesses"
            params = {
                "access_token": access_token,
                "fields": "id,name,created_by,permitted_tasks",
            }

            response = requests.get(bm_url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if "error" not in data:
                businesses = data.get("data", [])
                logger.info(f"  Found {len(businesses)} Business Manager(s)")

                for bm in businesses:
                    bm_id = bm.get("id")
                    bm_name = bm.get("name")
                    logger.info(f"  Checking BM: {bm_name} (ID: {bm_id})")

                    # Get BM's owned objects
                    try:
                        assets_url = f"{graph_url}/{bm_id}/owned_objects"
                        assets_params = {
                            "access_token": access_token,
                            "type": "INSTAGRAM_ACCOUNT",
                            "fields": "id,username,name,account_type",
                        }

                        assets_response = requests.get(
                            assets_url, params=assets_params, timeout=30
                        )
                        assets_response.raise_for_status()
                        assets_data = assets_response.json()

                        if "error" not in assets_data:
                            accounts = assets_data.get("data", [])
                            if accounts:
                                ig_account = accounts[0]
                                logger.info(
                                    f"✓ Found via BM owned_objects: @{ig_account.get('username')}"
                                )
                                return {
                                    "instagram_business_id": ig_account.get("id"),
                                    "page_id": None,
                                    "page_name": None,
                                    "instagram_username": ig_account.get("username"),
                                    "instagram_name": ig_account.get("name"),
                                    "account_type": ig_account.get(
                                        "account_type", "BUSINESS"
                                    ),
                                    "business_manager_id": bm_id,
                                    "business_manager_name": bm_name,
                                }, None
                    except requests.HTTPError as e:
                        try:
                            err = (
                                e.response.json()
                                .get("error", {})
                                .get("message", str(e))
                            )
                            logger.warning(f"    owned_objects failed: {err}")
                        except:
                            logger.warning(f"    owned_objects failed: {e}")

                    # Try getting accounts via /objects endpoint
                    try:
                        logger.info(f"  Trying /objects endpoint...")
                        objects_url = f"{graph_url}/{bm_id}/objects"
                        objects_params = {
                            "access_token": access_token,
                            "type": "instagram_accounts",
                            "fields": "id,username,name,account_type",
                        }

                        objects_response = requests.get(
                            objects_url, params=objects_params, timeout=30
                        )
                        objects_response.raise_for_status()
                        objects_data = objects_response.json()

                        if "error" not in objects_data:
                            accounts = objects_data.get("data", [])
                            if accounts:
                                ig_account = accounts[0]
                                logger.info(
                                    f"✓ Found via BM objects: @{ig_account.get('username')}"
                                )
                                return {
                                    "instagram_business_id": ig_account.get("id"),
                                    "page_id": None,
                                    "page_name": None,
                                    "instagram_username": ig_account.get("username"),
                                    "instagram_name": ig_account.get("name"),
                                    "account_type": ig_account.get(
                                        "account_type", "BUSINESS"
                                    ),
                                    "business_manager_id": bm_id,
                                    "business_manager_name": bm_name,
                                }, None
                    except requests.HTTPError as e:
                        try:
                            err = (
                                e.response.json()
                                .get("error", {})
                                .get("message", str(e))
                            )
                            logger.warning(f"    objects failed: {err}")
                        except:
                            pass

        except Exception as e:
            logger.warning(f"  BM info fetch failed: {e}")

    except Exception as e:
        logger.info(f"BM assignment discovery failed: {e}")

    # Method 5: Direct query the Instagram account if we can infer it from previous errors
    # The error logs showed account ID 17841446380066229 - try to access it directly
    # with the understanding that the user must have access to it
    try:
        logger.info("Attempting to access Instagram account directly...")

        # Common Instagram account ID patterns for Business Manager owned accounts
        # Try to get any Instagram account the user has access to via /me/ids_for_apps
        # or check assigned accounts via /me/accounts with different fields

        # Try getting Instagram accounts via user's accounts with expanded fields
        try:
            logger.info("  Trying /me/accounts with instagram_business_account...")
            accounts_url = f"{graph_url}/me/accounts"
            params = {
                "access_token": access_token,
                "fields": "id,name,instagram_business_account{id,username,name,account_type}",
                "limit": 100,
            }

            response = requests.get(accounts_url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if "error" not in data:
                pages = data.get("data", [])
                logger.info(f"  Found {len(pages)} Facebook Pages")

                for page in pages:
                    ig_data = page.get("instagram_business_account")
                    if ig_data:
                        logger.info(
                            f"✓ Found Instagram via Page '{page.get('name')}': @{ig_data.get('username')}"
                        )
                        return {
                            "instagram_business_id": ig_data.get("id"),
                            "page_id": page.get("id"),
                            "page_name": page.get("name"),
                            "instagram_username": ig_data.get("username"),
                            "instagram_name": ig_data.get("name"),
                            "account_type": ig_data.get("account_type", "BUSINESS"),
                        }, None
        except requests.HTTPError as e:
            try:
                err = e.response.json().get("error", {}).get("message", str(e))
                logger.warning(f"  /me/accounts with IG fields failed: {err}")
            except:
                logger.warning(f"  /me/accounts with IG fields failed: {e}")

        # Try to fetch the Instagram account we saw in the error (if user has access)
        # Note: This will only work if the token has explicit access to this account
        inferred_ids = ["17841446380066229"]  # From your error logs

        for ig_id in inferred_ids:
            try:
                logger.info(f"  Trying direct access to account ID: {ig_id}...")
                ig_url = f"{graph_url}/{ig_id}"
                params = {
                    "access_token": access_token,
                    "fields": "id,username,name,account_type",
                }

                response = requests.get(ig_url, params=params, timeout=30)
                response.raise_for_status()
                data = response.json()

                if "error" not in data and data.get("id"):
                    logger.info(
                        f"✓ Successfully accessed account directly: @{data.get('username')}"
                    )
                    return {
                        "instagram_business_id": data.get("id"),
                        "page_id": None,
                        "page_name": None,
                        "instagram_username": data.get("username"),
                        "instagram_name": data.get("name"),
                        "account_type": data.get("account_type", "BUSINESS"),
                    }, None
            except requests.HTTPError:
                # Expected to fail if user doesn't have direct access
                pass

    except Exception as e:
        logger.info(f"Direct access attempt failed: {e}")

    # Method 6: Query /me with instagram_business_account field
    try:
        logger.info("Trying /me with instagram_business_account field...")
        me_url = f"{graph_url}/me"
        params = {
            "access_token": access_token,
            "fields": "id,name,instagram_business_account{id,username,name,account_type}",
        }

        response = requests.get(me_url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        if "error" not in data:
            ig_data = data.get("instagram_business_account")
            if ig_data:
                logger.info(
                    f"✓ Found via /me instagram_business_account: @{ig_data.get('username')}"
                )
                return {
                    "instagram_business_id": ig_data.get("id"),
                    "page_id": None,
                    "page_name": None,
                    "instagram_username": ig_data.get("username"),
                    "instagram_name": ig_data.get("name"),
                    "account_type": ig_data.get("account_type", "BUSINESS"),
                }, None
    except requests.HTTPError as e:
        try:
            err = e.response.json().get("error", {}).get("message", str(e))
            logger.warning(f"  /me with instagram_business_account failed: {err}")
        except:
            logger.warning(f"  /me with instagram_business_account failed: {e}")
    except Exception as e:
        logger.info(f"/me with instagram_business_account failed: {e}")

    # Debug: Check what permissions the token has
    try:
        logger.info("Checking token permissions...")
        perms_url = f"{graph_url}/me/permissions"
        perms_response = requests.get(
            perms_url, params={"access_token": access_token}, timeout=30
        )
        perms_data = perms_response.json()

        if "error" not in perms_data:
            permissions = [
                p.get("permission")
                for p in perms_data.get("data", [])
                if p.get("status") == "granted"
            ]
            logger.info(f"Token has permissions: {permissions}")
            if "business_management" not in permissions:
                logger.error("MISSING: 'business_management' permission not granted!")
                logger.error(
                    "Please add 'business_management' to your OAuth scopes and re-authenticate."
                )
        else:
            logger.warning(f"Could not check permissions: {perms_data.get('error')}")
    except Exception as e:
        logger.warning(f"Could not check permissions: {e}")

    # All methods failed
    return None, (
        "No Instagram Business or Creator account found. "
        "Please ensure your Instagram account is either:\n"
        "1. A Business account connected to a Facebook Page you admin, OR\n"
        "2. A Creator account with appropriate permissions, OR\n"
        "3. Owned by a Business Manager you have access to\n\n"
        "TROUBLESHOOTING:\n"
        "- Ensure you have 'business_management' scope in your OAuth permissions\n"
        "- Verify your user has access to the Instagram account in Business Manager\n"
        "- The app automatically discovers all accessible accounts - no config needed"
    )


# ============================================================================
# Webhook Handler Functions
# ============================================================================


def verify_webhook_signature(
    app_secret: str, payload: bytes, signature_header: str
) -> bool:
    """
    Verify the X-Hub-Signature-256 header using HMAC-SHA256.
    
    Per Meta documentation:
    - Generate SHA256 signature using payload and App Secret
    - Compare to signature in X-Hub-Signature-256 header (after 'sha256=')
    """
    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected_signature = signature_header[7:]  # Remove 'sha256=' prefix
    
    # Calculate signature using HMAC-SHA256
    calculated_signature = hmac.new(
        app_secret.encode("utf-8"), payload, hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected_signature, calculated_signature)


def parse_comment_event(change_data: dict) -> dict:
    """Extract comment details from webhook change data."""
    value = change_data.get("value", {})
    from_data = value.get("from", {})

    # Debug: log the actual structure received
    logger.debug(f"Parsing comment event. Keys in value: {list(value.keys())}")
    logger.debug(f"From data: {from_data}")

    # Instagram webhooks have different field names
    # Try multiple possible field names
    return {
        "sender_id": from_data.get("id") or value.get("from_id", "unknown"),
        "sender_username": from_data.get("username")
        or value.get("from_name", "unknown"),
        "text": value.get("text") or value.get("message", ""),
        "media_id": value.get("media_id") or value.get("post_id", ""),
        "comment_id": value.get("comment_id") or value.get("id", ""),
        "timestamp": value.get("created_time") or value.get("timestamp"),
        "field": change_data.get("field", "unknown"),
    }


def process_comment_event(comment_info: dict) -> None:
    """Process a comment/mention event."""
    timestamp_str = "unknown"
    if comment_info.get("timestamp"):
        try:
            dt = datetime.fromtimestamp(int(comment_info["timestamp"]))
            timestamp_str = dt.isoformat()
        except (ValueError, TypeError):
            timestamp_str = str(comment_info["timestamp"])

    # Log to main app log
    logger.info(
        f"Instagram {comment_info['field'].upper()} event: "
        f"from={comment_info['sender_username']} ({comment_info['sender_id']}), "
        f"media_id={comment_info['media_id']}, "
        f"comment_id={comment_info['comment_id']}, "
        f"timestamp={timestamp_str}"
    )

    # Log to dedicated comments log file (structured format)
    comment_logger.info(
        f"EVENT={comment_info['field'].upper()} | "
        f"from_id={comment_info['sender_id']} | "
        f"from_username={comment_info['sender_username']} | "
        f"media_id={comment_info['media_id']} | "
        f"comment_id={comment_info['comment_id']} | "
        f"timestamp={timestamp_str} | "
        f"text={comment_info['text']!r}"
    )

    # TODO: Add your custom processing logic here
    # Examples:
    # - Send auto-reply
    # - Store in database
    # - Queue for async processing
    pass


# ============================================================================
# Route Handlers
# ============================================================================


def create_auth_routes(app: Flask) -> None:
    """Create OAuth authentication routes."""

    @app.route("/instagram/auth/meta", methods=["GET"])
    def initiate_oauth() -> Response:
        """Initiate OAuth flow for Instagram Business Account authentication."""
        try:
            cleanup_expired_states()

            state = generate_state()
            code_verifier, code_challenge = generate_pkce_pair()
            store_state(state, code_verifier)

            auth_url = (
                f"https://www.facebook.com/{Config.META_API_VERSION}/dialog/oauth"
            )

            from urllib.parse import urlencode

            auth_params = {
                "client_id": Config.META_APP_ID,
                "redirect_uri": Config.META_REDIRECT_URI,
                "scope": ",".join(REQUIRED_SCOPES),
                "state": state,
                "response_type": "code",
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }

            full_auth_url = f"{auth_url}?{urlencode(auth_params)}"

            logger.info(f"Initiating OAuth flow with state: {state[:16]}...")
            return redirect(full_auth_url)

        except Exception as e:
            logger.exception("Failed to initiate OAuth flow")
            return get_error_redirect("Failed to initiate authentication")

    @app.route("/instagram/auth/callback", methods=["GET"])
    def oauth_callback() -> Response:
        """Handle OAuth callback from Meta."""
        error = request.args.get("error")
        error_description = request.args.get("error_description")

        if error:
            logger.warning(f"OAuth error from Meta: {error} - {error_description}")
            return get_error_redirect(
                f"Authorization denied: {error_description or error}"
            )

        code = request.args.get("code")
        state = request.args.get("state")

        if not code:
            logger.error("No authorization code in callback")
            return get_error_redirect("Missing authorization code")

        if not state:
            logger.error("No state parameter in callback")
            return get_error_redirect("Missing state parameter")

        is_valid_state, code_verifier = validate_and_consume_state(state)
        if not is_valid_state:
            logger.error("Invalid or expired state parameter")
            return get_error_redirect("Invalid or expired session")

        logger.info("State validated successfully, exchanging code for token")

        access_token, expires_in, token_error = exchange_code_for_token(
            code, code_verifier
        )

        if token_error:
            return get_error_redirect(token_error)

        if not access_token:
            return get_error_redirect("Failed to obtain access token")

        logger.info(
            "Short-lived token obtained (1 hour validity), exchanging for long-lived token..."
        )

        # Automatically exchange for long-lived token (60 days)
        long_lived_token, long_expires_in, exchange_error = (
            exchange_for_long_lived_token(access_token)
        )

        if long_lived_token:
            # Use long-lived token
            access_token = long_lived_token
            expires_in = long_expires_in
            logger.info("Using long-lived token (60 days validity)")
        else:
            # Fallback to short-lived token (log warning but continue)
            logger.warning(
                f"Long-lived token exchange failed: {exchange_error}. Using short-lived token (1 hour)."
            )

        logger.info("Fetching Instagram account details...")

        account_data, account_error = fetch_instagram_business_account(access_token)

        if account_error:
            return get_error_redirect(account_error)

        if not account_data:
            return get_error_redirect("Failed to fetch Instagram account")

        expires_at = None
        if expires_in:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        # Calculate days remaining for logging
        days_remaining = round(expires_in / 86400, 1) if expires_in else "unknown"

        global account_store
        account_store = {
            "access_token": access_token,
            "token_expires_at": expires_at.isoformat() if expires_at else None,
            "token_type": "long_lived" if long_lived_token else "short_lived",
            "days_remaining": days_remaining,
            "instagram_business_id": account_data["instagram_business_id"],
            "page_id": account_data.get("page_id"),
            "user_name": account_data.get("instagram_username")
            or account_data.get("instagram_name"),
            "account_type": account_data.get("account_type", "BUSINESS"),
            "business_manager_id": account_data.get("business_manager_id"),
            "business_manager_name": account_data.get("business_manager_name"),
            "connected_at": datetime.now(timezone.utc).isoformat(),
        }

        # Persist to database
        try:
            save_account(account_store)
            logger.info("Account saved to database")
        except Exception as e:
            logger.error(f"Failed to save account to database: {e}")

        logger.info(
            f"Successfully connected Instagram Business Account: "
            f"{account_data.get('instagram_username') or account_data['instagram_business_id']}"
        )

        return redirect("/instagram/auth/status")

    @app.route("/instagram/auth/status", methods=["GET"])
    def auth_status() -> Response:
        """Return current authentication status."""
        error = request.args.get("error")
        
        # In production with multiple workers, reload from DB to get latest state
        # Each worker has its own memory, so account_store may be stale
        global account_store
        try:
            db_account = load_account()
            if db_account:
                account_store.update(db_account)
        except Exception as e:
            logger.warning(f"Could not reload account from DB: {e}")

        is_authenticated = bool(
            account_store.get("access_token")
            and account_store.get("instagram_business_id")
        )

        token_expired = False
        expires_at_str = account_store.get("token_expires_at")
        if expires_at_str and is_authenticated:
            try:
                expires_at = datetime.fromisoformat(expires_at_str)
                token_expired = datetime.now(timezone.utc) > expires_at
            except ValueError:
                logger.warning(f"Invalid expiry format: {expires_at_str}")

        response_data = {
            "authenticated": is_authenticated and not token_expired,
            "has_valid_token": is_authenticated and not token_expired,
        }

        if error:
            response_data["error"] = error

        if is_authenticated:
            response_data["account"] = {
                "instagram_business_id": account_store.get("instagram_business_id"),
                "page_id": account_store.get("page_id"),
                "user_name": account_store.get("user_name"),
                "connected_at": account_store.get("connected_at"),
                "token_expires_at": account_store.get("token_expires_at"),
                "token_type": account_store.get("token_type", "unknown"),
                "days_remaining": account_store.get("days_remaining", "unknown"),
                "account_type": account_store.get(
                    "account_type", "unknown"
                ),  # BUSINESS or CREATOR
                "business_manager": (
                    {
                        "id": account_store.get("business_manager_id"),
                        "name": account_store.get("business_manager_name"),
                    }
                    if account_store.get("business_manager_id")
                    else None
                ),
            }

            if token_expired:
                response_data["account"]["token_status"] = "expired"

        return jsonify(response_data)

    @app.route("/instagram/auth/logout", methods=["POST"])
    def logout() -> Response:
        """Clear stored credentials and log out."""
        global account_store

        had_account = bool(account_store.get("access_token"))

        # Clear in-memory store
        account_store = {
            "access_token": None,
            "token_expires_at": None,
            "token_type": None,
            "days_remaining": None,
            "instagram_business_id": None,
            "page_id": None,
            "user_name": None,
            "account_type": None,
            "business_manager_id": None,
            "business_manager_name": None,
            "connected_at": None,
        }

        # Clear database
        try:
            clear_account()
            logger.info("Account cleared from database")
        except Exception as e:
            logger.error(f"Failed to clear account from database: {e}")

        session.clear()

        logger.info("User logged out, credentials cleared")

        return jsonify(
            {
                "success": True,
                "message": "Logged out successfully",
                "had_active_session": had_account,
            }
        )

    @app.route("/instagram/auth/debug", methods=["GET"])
    def auth_debug() -> Response:
        """
        Debug endpoint to check what resources the current token can access.
        This helps diagnose permission issues.
        """
        token = account_store.get("access_token")
        if not token:
            return (
                jsonify({"error": "No token available. Please authenticate first."}),
                401,
            )

        graph_url = f"https://graph.facebook.com/{Config.META_API_VERSION}"
        results = {
            "token_preview": token[:20] + "..." if len(token) > 20 else token,
            "tests": {},
        }

        # Test 1: /me
        try:
            r = requests.get(
                f"{graph_url}/me",
                params={"access_token": token, "fields": "id,name"},
                timeout=10,
            )
            results["tests"]["/me"] = {
                "status": r.status_code,
                "data": r.json() if r.status_code == 200 else r.text[:200],
            }
        except Exception as e:
            results["tests"]["/me"] = {"error": str(e)}

        # Test 2: /me/accounts
        try:
            r = requests.get(
                f"{graph_url}/me/accounts", params={"access_token": token}, timeout=10
            )
            results["tests"]["/me/accounts"] = {
                "status": r.status_code,
                "data": r.json() if r.status_code == 200 else r.text[:200],
            }
        except Exception as e:
            results["tests"]["/me/accounts"] = {"error": str(e)}

        # Test 3: /me/businesses
        try:
            r = requests.get(
                f"{graph_url}/me/businesses", params={"access_token": token}, timeout=10
            )
            results["tests"]["/me/businesses"] = {
                "status": r.status_code,
                "data": r.json() if r.status_code == 200 else r.text[:200],
            }
        except Exception as e:
            results["tests"]["/me/businesses"] = {"error": str(e)}

        # Test 4: /me/permissions
        try:
            r = requests.get(
                f"{graph_url}/me/permissions",
                params={"access_token": token},
                timeout=10,
            )
            results["tests"]["/me/permissions"] = {
                "status": r.status_code,
                "data": r.json() if r.status_code == 200 else r.text[:200],
            }
        except Exception as e:
            results["tests"]["/me/permissions"] = {"error": str(e)}

        # Test 5: Direct Instagram account (from error logs)
        try:
            ig_id = "17841446380066229"
            r = requests.get(
                f"{graph_url}/{ig_id}",
                params={"access_token": token, "fields": "id,username"},
                timeout=10,
            )
            results["tests"][f"/instagram_account/{ig_id}"] = {
                "status": r.status_code,
                "data": r.json() if r.status_code == 200 else r.text[:200],
            }
        except Exception as e:
            results["tests"][f"/instagram_account/{ig_id}"] = {"error": str(e)}

        return jsonify(results)

    @app.route("/webhooks/recent", methods=["GET"])
    def recent_webhooks_view() -> Response:
        """View recent webhook payloads for debugging."""
        return jsonify({"count": len(recent_webhooks), "webhooks": recent_webhooks})

    @app.route("/webhooks/test-signature", methods=["POST"])
    def test_signature() -> Response:
        """
        Test endpoint to verify signature calculation.
        Send a test payload and see how signature is calculated.
        """
        from flask import request
        
        raw_payload = request.get_data()
        signature_header = request.headers.get("X-Hub-Signature-256", "")
        
        # Calculate signature
        if isinstance(Config.META_APP_SECRET, str):
            secret = Config.META_APP_SECRET.encode("utf-8")
        else:
            secret = Config.META_APP_SECRET
            
        calculated = hmac.new(secret, raw_payload, hashlib.sha256).hexdigest()
        
        expected = signature_header[7:] if signature_header.startswith("sha256=") else "N/A"
        
        return jsonify({
            "app_secret_preview": Config.META_APP_SECRET[:10] + "..." if Config.META_APP_SECRET else "NOT SET",
            "payload_length": len(raw_payload),
            "payload_preview": raw_payload[:200].decode('utf-8', errors='replace') if raw_payload else "EMPTY",
            "signature_header": signature_header[:30] + "..." if signature_header else "NOT PROVIDED",
            "expected_sig": expected[:20] + "..." if expected != "N/A" else "N/A",
            "calculated_sig": calculated[:20] + "...",
            "match": expected == calculated if expected != "N/A" else False,
        })

    @app.route("/webhooks/signature-status", methods=["GET"])
    def signature_status() -> Response:
        """Check signature verification status."""
        return jsonify({
            "app_secret_configured": bool(Config.META_APP_SECRET),
            "app_secret_length": len(Config.META_APP_SECRET) if Config.META_APP_SECRET else 0,
            "app_secret_preview": Config.META_APP_SECRET[:10] + "..." if Config.META_APP_SECRET else "NOT SET",
        })

    @app.route("/instagram/auth/refresh", methods=["POST"])
    def refresh_token() -> Response:
        """
        Manually refresh the access token before expiry.

        Meta long-lived tokens can be refreshed (getting a new 60-day token)
        by calling the same exchange endpoint again.

        Returns:
            JSON with new token details or error.
        """
        global account_store

        current_token = account_store.get("access_token")
        if not current_token:
            return (
                jsonify({"success": False, "error": "No active token to refresh"}),
                401,
            )

        logger.info("Manual token refresh requested")

        # Exchange current token for a new long-lived token
        new_token, expires_in, error = exchange_for_long_lived_token(current_token)

        if not new_token:
            return (
                jsonify({"success": False, "error": f"Token refresh failed: {error}"}),
                500,
            )

        # Update account store with new token
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            if expires_in
            else None
        )
        days_remaining = round(expires_in / 86400, 1) if expires_in else "unknown"

        account_store["access_token"] = new_token
        account_store["token_expires_at"] = (
            expires_at.isoformat() if expires_at else None
        )
        account_store["token_type"] = "long_lived"
        account_store["days_remaining"] = days_remaining

        # Update database
        try:
            update_token(
                new_token,
                expires_at.isoformat() if expires_at else None,
                days_remaining,
            )
            logger.info("Token updated in database")
        except Exception as e:
            logger.error(f"Failed to update token in database: {e}")

        logger.info(f"Token refreshed successfully (valid for ~{days_remaining} days)")

        return jsonify(
            {
                "success": True,
                "message": "Token refreshed successfully",
                "token_type": "long_lived",
                "expires_at": expires_at.isoformat() if expires_at else None,
                "days_remaining": days_remaining,
            }
        )


def create_webhook_routes(app: Flask) -> None:
    """Create webhook routes."""

    @app.route("/instagram/webhook", methods=["GET"])
    def verify_webhook() -> tuple:
        """Handle Meta webhook verification challenge."""
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        if mode != "subscribe":
            logger.warning(f"Webhook verification failed: invalid mode '{mode}'")
            return jsonify({"error": "Invalid mode"}), 403

        if not Config.META_VERIFY_TOKEN:
            logger.error("Webhook verification failed: VERIFY_TOKEN not configured")
            return jsonify({"error": "Server configuration error"}), 500

        if token != Config.META_VERIFY_TOKEN:
            logger.warning("Webhook verification failed: token mismatch")
            return jsonify({"error": "Invalid verification token"}), 403

        logger.info("Webhook verification successful")
        return challenge, 200

    @app.route("/instagram/webhook", methods=["POST"])
    def handle_webhook_event() -> tuple:
        """Handle incoming webhook events from Instagram."""
        # Get raw body BEFORE any Flask processing
        raw_payload = request.get_data()
        signature_header = request.headers.get("X-Hub-Signature-256")

        if not Config.META_APP_SECRET:
            logger.error("Webhook processing failed: APP_SECRET not configured")
            return jsonify({"error": "Server configuration error"}), 500

        if not signature_header:
            logger.warning("Webhook processing failed: missing X-Hub-Signature-256 header")
            return jsonify({"error": "Missing signature header"}), 403

        # Verify signature using App Secret
        if not verify_webhook_signature(Config.META_APP_SECRET, raw_payload, signature_header):
            logger.warning("Webhook processing failed: invalid signature")
            return jsonify({"error": "Invalid signature"}), 403

        try:
            # Parse the raw payload we already got (don't read request stream again)
            import json
            try:
                payload = json.loads(raw_payload.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.warning(f"Webhook processing failed: invalid JSON payload: {e}")
                return jsonify({"error": "Invalid JSON payload"}), 400

            if not payload:
                logger.warning("Webhook processing failed: empty JSON payload")
                return jsonify({"error": "Invalid JSON payload"}), 400

            # Debug: log the raw payload structure
            logger.debug(f"Raw webhook payload: {payload}")

            # Store for debugging (keep last 10)
            global recent_webhooks
            recent_webhooks.append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "payload": payload,
                }
            )
            recent_webhooks = recent_webhooks[-10:]  # Keep only last 10

            if payload.get("object") != "instagram":
                logger.info(
                    f"Ignoring webhook for object type: {payload.get('object')}"
                )
                return (
                    jsonify({"status": "ignored", "reason": "not instagram object"}),
                    200,
                )

            entries = payload.get("entry", [])
            processed_count = 0

            for entry in entries:
                changes = entry.get("changes", [])

                for change in changes:
                    field = change.get("field", "")

                    if field in ("mentions", "comments"):
                        try:
                            comment_info = parse_comment_event(change)
                            process_comment_event(comment_info)
                            processed_count += 1
                        except Exception as e:
                            logger.error(
                                f"Error processing comment event: {e}", exc_info=True
                            )
                    else:
                        logger.debug(f"Ignoring unhandled field type: {field}")

            logger.info(f"Webhook processed successfully: {processed_count} events")

            return (
                jsonify({"status": "success", "processed_events": processed_count}),
                200,
            )

        except Exception as e:
            logger.error(f"Error processing webhook: {e}", exc_info=True)
            return jsonify({"error": "Internal server error"}), 500


# ============================================================================
# Application Factory
# ============================================================================


def validate_environment() -> None:
    """Validate required environment variables are set."""
    missing = []
    if not Config.META_APP_ID:
        missing.append("META_APP_ID")
    if not Config.META_APP_SECRET:
        missing.append("META_APP_SECRET")
    if not Config.META_REDIRECT_URI:
        missing.append("META_REDIRECT_URI")
    if not Config.META_VERIFY_TOKEN:
        missing.append("META_VERIFY_TOKEN")
    if not Config.SECRET_KEY:
        missing.append("FLASK_SECRET_KEY")

    if missing:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            f"Please copy .env.example to .env and fill in your credentials.\n"
            f"For Meta credentials, visit: https://developers.facebook.com/apps/"
        )


def create_app() -> Flask:
    """
    Application factory - creates and configures the Flask application.

    Returns:
        Configured Flask application instance.
    """
    # Load configuration from environment
    Config.META_APP_ID = os.environ.get("META_APP_ID", "")
    Config.META_APP_SECRET = os.environ.get("META_APP_SECRET", "")
    
    # Debug: Log if APP_SECRET is not set properly
    if not Config.META_APP_SECRET:
        logger.error("❌ CRITICAL: META_APP_SECRET is not set!")
    else:
        logger.info(f"✅ META_APP_SECRET loaded (length: {len(Config.META_APP_SECRET)})")
    Config.META_REDIRECT_URI = os.environ.get(
        "META_REDIRECT_URI", "http://localhost:8001/auth/callback"
    )
    Config.META_VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN", "")
    Config.SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "")


    # Validate environment
    validate_environment()

    # Create Flask app
    app = Flask(__name__)
    app.secret_key = Config.SECRET_KEY

    # Configure database
    app.config["DATABASE"] = os.path.join(
        os.path.dirname(__file__), "instance", "app.sqlite"
    )

    # Ensure instance folder exists
    os.makedirs(os.path.dirname(app.config["DATABASE"]), exist_ok=True)
    
    # Security: Block common vulnerability scanners
    @app.before_request
    def block_scanners():
        """Block common vulnerability scanner paths."""
        blocked_paths = [
            ".env", ".git", ".env.local", ".env.production",
            "admin/.env", "api/.env", "config/.env",
            "wp-admin", "wp-login", "phpmyadmin",
            ".DS_Store", "Thumbs.db",
            "@vite/client",  # Vite dev server probes
        ]
        path = request.path.lower()
        for blocked in blocked_paths:
            if blocked in path:
                return jsonify({"error": "Not found"}), 404
    
    # Security headers for all responses
    @app.after_request
    def add_security_headers(response):
        """Add security headers to all responses."""
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return response

    # Session cookie security settings
    app.config.update(
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=1),
    )

    # Initialize database and load account
    init_db_app(app)

    # Load account from database into memory (within app context)
    with app.app_context():
        reload_account_from_db()

    # Register routes
    create_auth_routes(app)
    create_webhook_routes(app)

    # Register legal pages blueprint
    app.register_blueprint(legal_bp)

    # Root endpoint - redirect to health or show API info
    @app.route("/", methods=["GET"])
    def root() -> Response:
        """Root endpoint - shows API information and available routes."""
        return jsonify(
            {
                "service": "Instagram Meta API Integration",
                "version": "1.0.0",
                "status": "running",
                "documentation": {
                    "oauth_flow": "GET /instagram/auth/meta",
                    "auth_status": "GET /instagram/auth/status",
                    "logout": "POST /instagram/auth/logout",
                    "token_refresh": "POST /instagram/auth/refresh",
                    "webhook": "GET/POST /instagram/webhook",
                    "health": "GET /health",
                },
                "legal": {
                    "privacy_policy": "GET /privacy",
                    "terms_of_service": "GET /terms",
                },
                "quick_start": {
                    "step_1": "Visit /instagram/auth/meta to connect your Instagram account",
                    "step_2": "Check /instagram/auth/status to verify connection",
                    "step_3": "Webhooks will be received at /instagram/webhook",
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    # Health check endpoint
    @app.route("/health", methods=["GET"])
    def health_check() -> Response:
        """Health check endpoint for monitoring."""
        return jsonify(
            {
                "status": "healthy",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "config": {
                    "app_id_configured": bool(Config.META_APP_ID),
                    "redirect_uri": Config.META_REDIRECT_URI,
                },
            }
        )

    # Error handlers
    from werkzeug.exceptions import NotFound
    
    @app.errorhandler(NotFound)
    def handle_not_found(e: NotFound) -> Response:
        """Handle 404 Not Found - return clean 404 without logging error."""
        return jsonify({"error": "Not found"}), 404
    
    @app.errorhandler(BadRequest)
    def handle_bad_request(e: BadRequest) -> Response:
        logger.warning(f"Bad request: {e}")
        return jsonify({"error": "Bad request", "message": str(e)}), 400

    @app.errorhandler(Exception)
    def handle_exception(e: Exception) -> Response:
        """Handle unexpected errors - but not 404s."""
        # Don't log 404s as errors (common with vulnerability scanners)
        if isinstance(e, NotFound):
            return jsonify({"error": "Not found"}), 404
        logger.exception("Unhandled exception")
        return jsonify({"error": "Internal server error"}), 500

    logger.info("Flask application created successfully")
    return app


# ============================================================================
# Development Server
# ============================================================================

if __name__ == "__main__":
    # Development server - use only for development
    # In production, use a proper WSGI server like gunicorn

    # Try to load .env file for development
    try:
        from dotenv import load_dotenv

        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path)
            print(f"Loaded environment from {env_path}")
    except ImportError:
        pass

    app = create_app()
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true",
    )
