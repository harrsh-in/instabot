"""
Secure Token Storage Module

Provides reversible encryption for access tokens using Fernet (symmetric encryption).
This module requires the cryptography library to be installed.
"""

import os
import base64
import logging
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)


class TokenStoreError(Exception):
    """Raised when token storage operations fail."""

    pass


class TokenStore:
    """
    Secure storage for access tokens using Fernet encryption.

    Features:
        - Tokens are encrypted at rest using Fernet (AES-128 in CBC mode with HMAC)
        - Encryption key is derived from FLASK_SECRET_KEY using PBKDF2
        - Tokens persist in database (encrypted) and memory cache
    """

    def __init__(self, secret_key: str):
        if not secret_key or len(secret_key) < 32:
            raise TokenStoreError(
                "SECRET_KEY must be at least 32 characters long for secure encryption"
            )

        self._memory_store = {}  # account_id -> token (runtime cache only)
        self._fernet = self._create_fernet(secret_key)

        if not self._fernet:
            raise TokenStoreError("Failed to initialize Fernet encryption")

        logger.info("TokenStore initialized with Fernet encryption")

    def _create_fernet(self, secret_key: str) -> Optional[Fernet]:
        """Create a Fernet instance from the secret key."""
        try:
            # Use PBKDF2 to derive a 32-byte key from the secret
            # Salt should be unique per deployment and kept secret
            salt = os.environ.get(
                "TOKEN_ENCRYPTION_SALT", "instagram_webhook_service_salt"
            ).encode()

            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(secret_key.encode()))
            return Fernet(key)
        except Exception as e:
            logger.error(f"Failed to create Fernet instance: {e}")
            return None

    def encrypt(self, token: str) -> str:
        """
        Encrypt a token for database storage.

        Args:
            token: The access token to encrypt

        Returns:
            Encrypted token string with prefix

        Raises:
            TokenStoreError: If encryption fails
        """
        if not self._fernet:
            raise TokenStoreError("Encryption not initialized")

        if not token:
            raise TokenStoreError("Cannot encrypt empty token")

        try:
            encrypted = self._fernet.encrypt(token.encode())
            return f"enc:{encrypted.decode()}"
        except Exception as e:
            logger.error(f"Token encryption failed: {e}")
            raise TokenStoreError(f"Failed to encrypt token: {e}")

    def decrypt(self, encrypted_token: str) -> Optional[str]:
        """
        Decrypt a token from database storage.

        Args:
            encrypted_token: Token string with encryption prefix

        Returns:
            Decrypted token or None if decryption fails

        Raises:
            TokenStoreError: If encryption is not initialized
        """
        if not self._fernet:
            raise TokenStoreError("Encryption not initialized")

        if not encrypted_token:
            return None

        # Check for encryption prefix
        if not encrypted_token.startswith("enc:"):
            logger.warning("Token has invalid format - expected encrypted token")
            return None

        try:
            ciphertext = encrypted_token[4:].encode()
            return self._fernet.decrypt(ciphertext).decode()
        except Exception as e:
            logger.error(f"Token decryption failed: {e}")
            return None

    def store(self, account_id: int, token: str) -> str:
        """
        Store a token securely and return encrypted version for database.

        Args:
            account_id: The account ID to associate with the token
            token: The access token to store

        Returns:
            Encrypted token string for database storage
        """
        # Encrypt for database storage
        encrypted = self.encrypt(token)

        # Store in memory cache for quick access
        self._memory_store[account_id] = token

        return encrypted

    def retrieve(self, account_id: int, encrypted_token: str) -> Optional[str]:
        """
        Retrieve a token securely.

        First checks memory cache, then decrypts from database if needed.

        Args:
            account_id: The account ID
            encrypted_token: Encrypted token from database

        Returns:
            The decrypted access token or None
        """
        # Check memory cache first
        if account_id in self._memory_store:
            return self._memory_store[account_id]

        # Decrypt from database
        if encrypted_token:
            token = self.decrypt(encrypted_token)
            if token:
                # Cache in memory for subsequent requests
                self._memory_store[account_id] = token
            return token

        return None

    def delete(self, account_id: int):
        """Remove a token from storage."""
        self._memory_store.pop(account_id, None)

    def clear(self):
        """Clear all tokens from memory cache."""
        self._memory_store.clear()

    def load_from_database(self, accounts):
        """
        Load tokens from database records into memory cache.

        Args:
            accounts: List of InstagramAccount objects with access_token_encrypted

        Returns:
            Number of tokens successfully loaded
        """
        loaded = 0
        for account in accounts:
            token = self.decrypt(account.access_token_encrypted)
            if token:
                self._memory_store[account.id] = token
                loaded += 1

        logger.info(f"Loaded {loaded} tokens into memory cache")
        return loaded


# Global instance (initialized in app factory)
_store: Optional[TokenStore] = None


def init_token_store(secret_key: str) -> TokenStore:
    """Initialize the global token store."""
    global _store
    _store = TokenStore(secret_key)
    return _store


def get_store() -> Optional[TokenStore]:
    """Get the global token store instance."""
    return _store
