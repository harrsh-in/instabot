"""
Database module for SQLite persistence.

Follows Flask tutorial pattern: https://flask.palletsprojects.com/en/stable/tutorial/database/
"""

import sqlite3
import json
from datetime import datetime
from flask import current_app, g


def get_db():
    """Connect to the application's configured database."""
    if "db" not in g:
        # No detect_types - store timestamps as strings to avoid parsing issues
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        # Enable WAL mode for better concurrency
        g.db.execute("PRAGMA journal_mode=WAL;")

    return g.db


def close_db(e=None):
    """Close the database connection."""
    db = g.pop("db", None)

    if db is not None:
        db.close()


def init_db():
    """Create the database tables."""
    db = get_db()

    # Create account table
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS account (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            access_token TEXT NOT NULL,
            token_expires_at TIMESTAMP,
            token_type TEXT,
            days_remaining REAL,
            instagram_business_id TEXT NOT NULL,
            page_id TEXT,
            user_name TEXT,
            account_type TEXT,
            business_manager_id TEXT,
            business_manager_name TEXT,
            connected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    db.commit()


def init_app(app):
    """Register database functions with the Flask app."""
    app.teardown_appcontext(close_db)
    # Initialize database within app context
    with app.app_context():
        init_db()


# Account CRUD operations


def save_account(account_data: dict) -> None:
    """
    Save or update account in database.

    Args:
        account_data: Dictionary containing account information
    """
    db = get_db()

    # Check if account already exists
    existing = db.execute("SELECT id FROM account WHERE id = 1").fetchone()

    if existing:
        # Update existing account
        db.execute(
            """
            UPDATE account SET
                access_token = ?,
                token_expires_at = ?,
                token_type = ?,
                days_remaining = ?,
                instagram_business_id = ?,
                page_id = ?,
                user_name = ?,
                account_type = ?,
                business_manager_id = ?,
                business_manager_name = ?,
                connected_at = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
            """,
            (
                account_data.get("access_token"),
                account_data.get("token_expires_at"),
                account_data.get("token_type"),
                account_data.get("days_remaining"),
                account_data.get("instagram_business_id"),
                account_data.get("page_id"),
                account_data.get("user_name"),
                account_data.get("account_type"),
                account_data.get("business_manager_id"),
                account_data.get("business_manager_name"),
                account_data.get("connected_at"),
            ),
        )
    else:
        # Insert new account
        db.execute(
            """
            INSERT INTO account (
                id, access_token, token_expires_at, token_type, days_remaining,
                instagram_business_id, page_id, user_name, account_type,
                business_manager_id, business_manager_name, connected_at
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_data.get("access_token"),
                account_data.get("token_expires_at"),
                account_data.get("token_type"),
                account_data.get("days_remaining"),
                account_data.get("instagram_business_id"),
                account_data.get("page_id"),
                account_data.get("user_name"),
                account_data.get("account_type"),
                account_data.get("business_manager_id"),
                account_data.get("business_manager_name"),
                account_data.get("connected_at"),
            ),
        )

    db.commit()


def load_account() -> dict | None:
    """
    Load account from database.

    Returns:
        Account dictionary or None if no account exists
    """
    db = get_db()

    row = db.execute("SELECT * FROM account WHERE id = 1").fetchone()

    if row is None:
        return None

    return {
        "access_token": row["access_token"],
        "token_expires_at": row["token_expires_at"],
        "token_type": row["token_type"],
        "days_remaining": row["days_remaining"],
        "instagram_business_id": row["instagram_business_id"],
        "page_id": row["page_id"],
        "user_name": row["user_name"],
        "account_type": row["account_type"],
        "business_manager_id": row["business_manager_id"],
        "business_manager_name": row["business_manager_name"],
        "connected_at": row["connected_at"],
    }


def clear_account() -> None:
    """Delete account from database (logout)."""
    db = get_db()
    db.execute("DELETE FROM account WHERE id = 1")
    db.commit()


def update_token(access_token: str, expires_at: str, days_remaining: float) -> None:
    """Update just the token fields (for refresh)."""
    db = get_db()
    db.execute(
        """
        UPDATE account SET
            access_token = ?,
            token_expires_at = ?,
            days_remaining = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
        """,
        (access_token, expires_at, days_remaining),
    )
    db.commit()
