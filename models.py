"""
Database models for Instagram Webhook Service.
SQLite with SQLAlchemy - production-grade with proper constraints.
"""

import datetime
import logging
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import String, DateTime, Text, Boolean, Integer
from sqlalchemy.orm import validates

db = SQLAlchemy()
logger = logging.getLogger(__name__)


class InstagramAccount(db.Model):
    """
    Stores the authenticated Instagram Business Account.
    Each user can have one connected Instagram account.
    """
    __tablename__ = 'instagram_accounts'
    
    id = db.Column(Integer, primary_key=True)
    
    # Instagram Graph API identifiers
    instagram_business_account_id = db.Column(
        String(255), 
        unique=True, 
        nullable=False, 
        index=True
    )
    instagram_username = db.Column(String(255), nullable=True)
    
    # Facebook Page connection (required for Instagram Graph API)
    facebook_page_id = db.Column(String(255), nullable=False, index=True)
    facebook_page_name = db.Column(String(255), nullable=True)
    
    # OAuth tokens (encrypted at rest with Fernet)
    access_token_encrypted = db.Column(Text, nullable=False)
    token_expires_at = db.Column(DateTime, nullable=True)
    
    # Webhook subscription status
    webhook_subscribed = db.Column(Boolean, default=False, nullable=False)
    
    # Timestamps
    created_at = db.Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = db.Column(
        DateTime, 
        default=datetime.datetime.utcnow, 
        onupdate=datetime.datetime.utcnow,
        nullable=False
    )
    last_used_at = db.Column(DateTime, nullable=True)
    
    @validates('instagram_business_account_id')
    def validate_ig_id(self, key, value):
        if not value or not value.strip():
            raise ValueError("Instagram Business Account ID is required")
        return value.strip()
    
    @validates('facebook_page_id')
    def validate_page_id(self, key, value):
        if not value or not value.strip():
            raise ValueError("Facebook Page ID is required")
        return value.strip()
    
    def set_access_token(self, token: str, token_store):
        """
        Encrypt and store the access token.
        
        Args:
            token: The access token to store
            token_store: TokenStore instance for encryption
        
        Raises:
            ValueError: If token or token_store is invalid
        """
        if not token:
            raise ValueError("Access token cannot be empty")
        if not token_store:
            raise ValueError("Token store is required")
        
        self.access_token_encrypted = token_store.store(self.id, token)
    
    def get_access_token(self, token_store) -> str:
        """
        Retrieve the decrypted access token.
        
        Args:
            token_store: TokenStore instance for decryption
        
        Returns:
            The decrypted access token or None
        
        Raises:
            ValueError: If token_store is invalid
        """
        if not token_store:
            raise ValueError("Token store is required")
        
        return token_store.retrieve(self.id, self.access_token_encrypted)
    
    @property
    def is_token_expired(self) -> bool:
        """Check if the token is expired."""
        if not self.token_expires_at:
            return False
        return datetime.datetime.utcnow() >= self.token_expires_at
    
    def to_dict(self):
        """Return account data as dictionary (sensitive data excluded)."""
        return {
            'id': self.id,
            'instagram_business_account_id': self.instagram_business_account_id,
            'instagram_username': self.instagram_username,
            'facebook_page_id': self.facebook_page_id,
            'facebook_page_name': self.facebook_page_name,
            'webhook_subscribed': self.webhook_subscribed,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None,
        }
    
    def __repr__(self):
        return f"<InstagramAccount {self.instagram_username or self.instagram_business_account_id}>"


class WebhookEvent(db.Model):
    """
    Stores incoming webhook events for logging and auditing.
    Keeps a history of all comments/mentions received.
    """
    __tablename__ = 'webhook_events'
    
    id = db.Column(Integer, primary_key=True)
    
    # Event details from Meta
    event_id = db.Column(
        String(255), 
        unique=True, 
        nullable=False, 
        index=True
    )
    event_type = db.Column(String(50), nullable=False, index=True)
    
    # Media/Post info
    media_id = db.Column(String(255), nullable=True, index=True)
    media_type = db.Column(String(50), nullable=True)
    
    # Comment info
    comment_id = db.Column(String(255), nullable=True, index=True)
    comment_text = db.Column(Text, nullable=True)
    
    # Sender info (who commented/mentioned)
    sender_id = db.Column(String(255), nullable=True, index=True)
    sender_username = db.Column(String(255), nullable=True)
    
    # Raw webhook payload (for debugging and audit)
    raw_payload = db.Column(Text, nullable=False)
    
    # Processing status
    processed = db.Column(Boolean, default=False, nullable=False)
    processed_at = db.Column(DateTime, nullable=True)
    auto_reply_sent = db.Column(Boolean, default=False, nullable=False)
    auto_reply_message_id = db.Column(String(255), nullable=True)
    error_message = db.Column(Text, nullable=True)
    
    # Timestamps
    received_at = db.Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    created_at = db.Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    
    @validates('event_id')
    def validate_event_id(self, key, value):
        if not value or not value.strip():
            raise ValueError("Event ID is required")
        return value.strip()
    
    def to_dict(self):
        """Return event data as dictionary."""
        return {
            'id': self.id,
            'event_id': self.event_id,
            'event_type': self.event_type,
            'media_id': self.media_id,
            'media_type': self.media_type,
            'comment_id': self.comment_id,
            'comment_text': self.comment_text,
            'sender_id': self.sender_id,
            'sender_username': self.sender_username,
            'processed': self.processed,
            'processed_at': self.processed_at.isoformat() if self.processed_at else None,
            'auto_reply_sent': self.auto_reply_sent,
            'received_at': self.received_at.isoformat() if self.received_at else None,
        }
    
    def __repr__(self):
        return f"<WebhookEvent {self.event_type} {self.event_id}>"


class AutoReplyLog(db.Model):
    """
    Logs of auto-replies sent to users.
    Maintains audit trail of all automated responses.
    """
    __tablename__ = 'auto_reply_logs'
    
    id = db.Column(Integer, primary_key=True)
    
    # Reference to webhook event
    webhook_event_id = db.Column(
        Integer, 
        db.ForeignKey('webhook_events.id'), 
        nullable=True
    )
    
    # Recipient info
    recipient_id = db.Column(String(255), nullable=False, index=True)
    recipient_username = db.Column(String(255), nullable=True)
    
    # Message details
    message_text = db.Column(Text, nullable=False)
    message_id = db.Column(String(255), nullable=True)
    
    # Status
    sent_at = db.Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    success = db.Column(Boolean, default=True, nullable=False)
    error_message = db.Column(Text, nullable=True)
    
    def to_dict(self):
        """Return log data as dictionary."""
        return {
            'id': self.id,
            'recipient_id': self.recipient_id,
            'recipient_username': self.recipient_username,
            'message_text': self.message_text,
            'message_id': self.message_id,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'success': self.success,
        }
    
    def __repr__(self):
        return f"<AutoReplyLog {self.recipient_username} success={self.success}>"


def init_db(app):
    """Initialize the database with the Flask app."""
    db.init_app(app)
    
    with app.app_context():
        try:
            # Create tables if they don't exist
            # checkfirst=True prevents errors if tables already exist
            db.create_all()
            logger.info("Database tables initialized")
        except Exception as e:
            # Log but don't fail - tables might already exist from another worker
            logger.warning(f"Database initialization note: {e}")
            # Continue - this is likely a race condition with multiple workers
            pass
