"""
Meta (Facebook/Instagram) Graph API Service Layer.
Handles all interactions with the Meta APIs with production-grade error handling.
"""

import requests
import hmac
import hashlib
import logging
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Meta API endpoints
META_GRAPH_API_BASE = "https://graph.facebook.com/v18.0"
META_OAUTH_BASE = "https://www.facebook.com/v18.0/dialog/oauth"
META_TOKEN_URL = "https://graph.facebook.com/v18.0/oauth/access_token"

# Request timeout in seconds
REQUEST_TIMEOUT = 30


@dataclass
class InstagramAccountInfo:
    """Data class for Instagram account information."""

    instagram_business_account_id: str
    instagram_username: str
    facebook_page_id: str
    facebook_page_name: str
    access_token: str
    token_expires_in: Optional[int] = None


class MetaAPIError(Exception):
    """Custom exception for Meta API errors."""

    def __init__(
        self,
        message: str,
        error_code: Optional[int] = None,
        error_subcode: Optional[int] = None,
    ):
        super().__init__(message)
        self.error_code = error_code
        self.error_subcode = error_subcode


class MetaService:
    """
    Service class for interacting with Meta's Graph API.
    Handles OAuth, webhook verification, and Instagram messaging.
    """

    def __init__(
        self, app_id: str, app_secret: str, verify_token: str, redirect_uri: str
    ):
        if not app_id or not app_secret:
            raise ValueError("App ID and App Secret are required")
        if not verify_token:
            raise ValueError("Verify token is required")
        if not redirect_uri:
            raise ValueError("Redirect URI is required")

        self.app_id = app_id
        self.app_secret = app_secret
        self.verify_token = verify_token
        self.redirect_uri = redirect_uri
        self.base_url = META_GRAPH_API_BASE

    def get_oauth_url(self, state: Optional[str] = None) -> str:
        """
        Generate the OAuth URL for Instagram account connection.

        Required permissions for Instagram Basic Display and Graph API:
        - instagram_business_basic: Read Instagram business account info
        - instagram_manage_comments: Manage comments on posts
        - instagram_manage_messages: Send/receive messages
        - instagram_basic: Basic profile access
        """
        # Instagram and Facebook permissions required
        # Matching the permissions shown in Meta dashboard (API setup with Facebook login)
        permissions = [
            "instagram_basic",
            "instagram_manage_messages",
            "pages_read_engagement",
            "pages_show_list",
            "business_management",
        ]

        scopes = ",".join(permissions)
        url = (
            f"{META_OAUTH_BASE}?"
            f"client_id={self.app_id}"
            f"&redirect_uri={self.redirect_uri}"
            f"&scope={scopes}"
            f"&response_type=code"
        )

        if state:
            url += f"&state={state}"

        return url

    def exchange_code_for_token(self, code: str) -> Tuple[str, Optional[int]]:
        """
        Exchange OAuth code for access token.

        Returns:
            Tuple of (access_token, expires_in_seconds)

        Raises:
            MetaAPIError: If token exchange fails
        """
        if not code:
            raise ValueError("Authorization code is required")

        params = {
            "client_id": self.app_id,
            "client_secret": self.app_secret,
            "code": code,
            "redirect_uri": self.redirect_uri,
        }

        try:
            response = requests.get(
                META_TOKEN_URL, params=params, timeout=REQUEST_TIMEOUT
            )
            data = response.json()

            if "error" in data:
                error = data["error"]
                raise MetaAPIError(
                    f"Token exchange failed: {error.get('message', 'Unknown error')}",
                    error_code=error.get("code"),
                    error_subcode=error.get("error_subcode"),
                )

            access_token = data.get("access_token")
            expires_in = data.get("expires_in")

            if not access_token:
                raise MetaAPIError("No access token in response")

            return access_token, expires_in

        except requests.Timeout:
            logger.error("Token exchange request timed out")
            raise MetaAPIError("Request timed out. Please try again.")
        except requests.RequestException as e:
            logger.error(f"Network error during token exchange: {e}")
            raise MetaAPIError(f"Network error: {str(e)}")

    def get_long_lived_token(self, short_lived_token: str) -> Tuple[str, int]:
        """
        Exchange short-lived token for long-lived token (60 days).

        Returns:
            Tuple of (access_token, expires_in_seconds)

        Raises:
            MetaAPIError: If exchange fails
        """
        if not short_lived_token:
            raise ValueError("Short-lived token is required")

        url = f"{META_GRAPH_API_BASE}/oauth/access_token"
        params = {
            "grant_type": "fb_exchange_token",
            "client_id": self.app_id,
            "client_secret": self.app_secret,
            "fb_exchange_token": short_lived_token,
        }

        try:
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            data = response.json()

            if "error" in data:
                error = data["error"]
                raise MetaAPIError(
                    f"Long-lived token exchange failed: {error.get('message')}",
                    error_code=error.get("code"),
                )

            access_token = data.get("access_token")
            expires_in = data.get("expires_in", 5184000)  # Default 60 days

            if not access_token:
                raise MetaAPIError("No access token received")

            return access_token, expires_in

        except requests.Timeout:
            logger.error("Long-lived token exchange timed out")
            raise MetaAPIError("Request timed out. Please try again.")
        except requests.RequestException as e:
            logger.error(f"Network error during long-lived token exchange: {e}")
            raise MetaAPIError(f"Network error: {str(e)}")

    def get_instagram_account_info(self, access_token: str) -> InstagramAccountInfo:
        """
        Get Instagram Business Account info from access token.

        Flow:
        1. Get user's Facebook pages
        2. Find page with connected Instagram Business Account
        3. Get Instagram account details

        Raises:
            MetaAPIError: If API calls fail or no account found
        """
        if not access_token:
            raise ValueError("Access token is required")

        # Step 1: Get user's pages
        pages = self._get_user_pages(access_token)

        if not pages:
            raise MetaAPIError(
                "No Facebook pages found. You need a Facebook Page connected to your Instagram Business account."
            )

        # Step 2: Find page with Instagram Business Account
        for page in pages:
            page_id = page.get("id")
            page_name = page.get("name")
            page_token = page.get("access_token")

            if not page_id:
                continue

            # Check if this page has an Instagram Business Account
            instagram_account = self._get_page_instagram_account(
                page_id, page_token or access_token
            )

            if instagram_account:
                return InstagramAccountInfo(
                    instagram_business_account_id=instagram_account["id"],
                    instagram_username=instagram_account.get("username", ""),
                    facebook_page_id=page_id,
                    facebook_page_name=page_name,
                    access_token=page_token or access_token,
                )

        raise MetaAPIError(
            "No Instagram Business Account found. "
            "Ensure your Instagram account is connected to a Facebook Page and is a Business/Creator account."
        )

    def _get_user_pages(self, access_token: str) -> list:
        """Get list of Facebook pages the user manages."""
        url = f"{META_GRAPH_API_BASE}/me/accounts"
        params = {"access_token": access_token, "fields": "id,name,access_token"}

        try:
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            data = response.json()

            if "error" in data:
                raise MetaAPIError(
                    f"Failed to get pages: {data['error'].get('message')}"
                )

            return data.get("data", [])

        except requests.Timeout:
            logger.error("Get pages request timed out")
            raise MetaAPIError("Request timed out")
        except requests.RequestException as e:
            logger.error(f"Network error getting pages: {e}")
            raise MetaAPIError(f"Network error: {str(e)}")

    def _get_page_instagram_account(
        self, page_id: str, access_token: str
    ) -> Optional[Dict[str, Any]]:
        """Get Instagram Business Account connected to a Facebook Page."""
        if not page_id or not access_token:
            return None

        url = f"{META_GRAPH_API_BASE}/{page_id}"
        params = {
            "access_token": access_token,
            "fields": "instagram_business_account{username,ig_id}",
        }

        try:
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            data = response.json()

            if "error" in data:
                logger.warning(
                    f"Error getting Instagram account for page {page_id}: {data['error'].get('message')}"
                )
                return None

            instagram_business_account = data.get("instagram_business_account")
            if instagram_business_account:
                return {
                    "id": instagram_business_account.get("id"),
                    "username": instagram_business_account.get("username"),
                    "ig_id": instagram_business_account.get("ig_id"),
                }

            return None

        except requests.Timeout:
            logger.warning(f"Timeout getting Instagram account for page {page_id}")
            return None
        except requests.RequestException as e:
            logger.error(f"Network error getting Instagram account: {e}")
            return None

    def reply_to_comment(
        self, comment_id: str, message: str, access_token: str
    ) -> Dict[str, Any]:
        """
        Reply to a comment on an Instagram post.

        Args:
            comment_id: The ID of the comment to reply to
            message: The reply message text
            access_token: Valid access token

        Returns:
            API response dict containing the reply ID

        Raises:
            MetaAPIError: If the API call fails
        """
        if not comment_id:
            raise ValueError("Comment ID is required")
        if not message or not message.strip():
            raise ValueError("Message cannot be empty")
        if not access_token:
            raise ValueError("Access token is required")

        url = f"{META_GRAPH_API_BASE}/{comment_id}/replies"

        params = {"message": message.strip(), "access_token": access_token}

        try:
            response = requests.post(url, params=params, timeout=REQUEST_TIMEOUT)
            data = response.json()

            if "error" in data:
                error = data["error"]
                raise MetaAPIError(
                    f"Failed to reply to comment: {error.get('message')}",
                    error_code=error.get("code"),
                )

            logger.info(f"Reply sent successfully to comment {comment_id}")
            return data

        except requests.Timeout:
            logger.error(f"Reply to comment {comment_id} timed out")
            raise MetaAPIError("Request timed out")
        except requests.RequestException as e:
            logger.error(f"Network error replying to comment: {e}")
            raise MetaAPIError(f"Network error: {str(e)}")

    def get_comment_details(self, comment_id: str, access_token: str) -> Dict[str, Any]:
        """Get details about a specific comment."""
        if not comment_id:
            raise ValueError("Comment ID is required")
        if not access_token:
            raise ValueError("Access token is required")

        url = f"{META_GRAPH_API_BASE}/{comment_id}"
        params = {
            "access_token": access_token,
            "fields": "id,text,username,timestamp,like_count",
        }

        try:
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            data = response.json()

            if "error" in data:
                raise MetaAPIError(
                    f"Failed to get comment details: {data['error'].get('message')}"
                )

            return data

        except requests.Timeout:
            logger.error("Get comment details timed out")
            raise MetaAPIError("Request timed out")
        except requests.RequestException as e:
            logger.error(f"Network error getting comment details: {e}")
            raise MetaAPIError(f"Network error: {str(e)}")

    def _escape_unicode_for_signature(self, payload_bytes: bytes) -> bytes:
        """
        Escape non-ASCII characters in payload for signature calculation.

        Meta calculates signatures on the escaped unicode version of the payload,
        with lowercase hex digits (e.g., äöå becomes \u00e4\u00f6\u00e5).

        Source: https://stackoverflow.com/a/38392805
        """
        try:
            # Decode as UTF-8
            text = payload_bytes.decode("utf-8")

            # Escape non-ASCII characters
            escaped = []
            for char in text:
                if ord(char) > 127:
                    escaped.append(f"\\u{ord(char):04x}")
                else:
                    escaped.append(char)

            return "".join(escaped).encode("utf-8")
        except UnicodeDecodeError:
            # If we can't decode as UTF-8, return original
            return payload_bytes

    def verify_webhook_signature(
        self, payload: bytes, signature: str, app_secret: str
    ) -> bool:
        """
        Verify that the webhook payload was sent by Meta.

        Meta sends a X-Hub-Signature-256 header containing a SHA256 HMAC
        of the payload, using the app secret as the key.

        Args:
            payload: Raw request body bytes
            signature: X-Hub-Signature-256 header value
            app_secret: Meta App Secret

        Returns:
            True if signature is valid, False otherwise
        """
        if not signature:
            logger.warning("No signature provided in webhook request")
            return False

        if not app_secret:
            logger.error("App secret not configured for signature verification")
            return False

        if not payload:
            logger.warning("Empty payload for signature verification")
            return False

        # Signature format: "sha256=<hash>"
        if "=" in signature:
            _, expected_hash = signature.split("=", 1)
        else:
            expected_hash = signature

        def compute_hash(data: bytes) -> str:
            """Compute HMAC-SHA256 hash."""
            return hmac.new(
                app_secret.encode("utf-8"), data, hashlib.sha256
            ).hexdigest()

        try:
            # Try 1: Raw payload as-is
            computed_hash_raw = compute_hash(payload)

            # Try 2: Unicode escaped version (for non-ASCII characters)
            escaped_payload = self._escape_unicode_for_signature(payload)
            computed_hash_escaped = compute_hash(escaped_payload)

        except Exception as e:
            logger.error(f"Error computing HMAC: {e}")
            return False

        # Debug logging for troubleshooting
        logger.info(f"Signature verification:")
        logger.info(f"  - Header signature: {signature[:30]}...")
        logger.info(f"  - Expected hash: {expected_hash[:30]}...")
        logger.info(f"  - Computed (raw): {computed_hash_raw[:30]}...")
        logger.info(f"  - Computed (escaped): {computed_hash_escaped[:30]}...")
        logger.info(f"  - Payload length: {len(payload)} bytes")
        logger.info(f"  - Escaped length: {len(escaped_payload)} bytes")
        logger.info(f"  - App secret length: {len(app_secret)} chars")

        # Use constant-time comparison to prevent timing attacks
        is_valid_raw = hmac.compare_digest(
            computed_hash_raw.lower(), expected_hash.lower()
        )
        is_valid_escaped = hmac.compare_digest(
            computed_hash_escaped.lower(), expected_hash.lower()
        )

        if is_valid_raw:
            logger.info("Signature verified using raw payload")
            return True
        elif is_valid_escaped:
            logger.info("Signature verified using unicode-escaped payload")
            return True
        else:
            logger.warning(
                "Webhook signature verification failed (both raw and escaped)"
            )
            return False

    def verify_subscription_challenge(
        self, mode: str, token: str, challenge: str
    ) -> Optional[str]:
        """
        Verify webhook subscription challenge during setup.

        Returns:
            The challenge string if verification succeeds, None otherwise.
        """
        if not mode or not token or not challenge:
            logger.warning("Missing parameters in subscription challenge")
            return None

        if mode == "subscribe" and token == self.verify_token:
            logger.info("Webhook subscription challenge verified")
            return challenge

        logger.warning("Webhook subscription challenge failed")
        return None

    def get_token_expiration(self, access_token: str) -> Optional[datetime]:
        """Check when a token expires."""
        if not access_token:
            return None

        url = f"{META_GRAPH_API_BASE}/debug_token"
        params = {
            "input_token": access_token,
            "access_token": f"{self.app_id}|{self.app_secret}",
        }

        try:
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            data = response.json()

            if "error" in data:
                logger.error(f"Token debug failed: {data['error']}")
                return None

            token_data = data.get("data", {})
            expires_at = token_data.get("expires_at")

            if expires_at:
                return datetime.fromtimestamp(expires_at)

            return None

        except requests.Timeout:
            logger.error("Token expiration check timed out")
            return None
        except requests.RequestException as e:
            logger.error(f"Error checking token expiration: {e}")
            return None
