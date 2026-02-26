"""
Webhook handlers for Meta Instagram events.
Handles comment notifications and auto-replies with production-grade error handling.
"""

import json
import logging
from flask import Blueprint, request, jsonify, current_app
from datetime import datetime
from models import db, InstagramAccount, WebhookEvent, AutoReplyLog
from meta_service import MetaService, MetaAPIError
from token_store import get_store

logger = logging.getLogger(__name__)
webhook_bp = Blueprint("webhooks", __name__)

# Auto-reply message template - customize as needed
AUTO_REPLY_MESSAGE = """👋 Thanks for your comment! 

This is an automated response. I'll get back to you personally soon! 

Have a great day! 😊"""

# Maximum message length for Instagram comments
MAX_MESSAGE_LENGTH = 1000


def truncate_message(message: str, max_length: int = MAX_MESSAGE_LENGTH) -> str:
    """Truncate message to maximum allowed length."""
    if len(message) <= max_length:
        return message
    return message[: max_length - 3] + "..."


@webhook_bp.route("/webhook/instagram", methods=["GET", "POST"])
def instagram_webhook():
    """
    Handle Instagram webhook events.

    GET: Handle subscription verification challenge
    POST: Handle incoming webhook events (comments, mentions, etc.)
    """
    meta_service: MetaService = current_app.config.get("META_SERVICE")
    app_secret = current_app.config.get("META_APP_SECRET")

    if request.method == "GET":
        # Subscription verification challenge
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        if not meta_service:
            logger.error("MetaService not configured")
            return "Service not configured", 500

        result = meta_service.verify_subscription_challenge(mode, token, challenge)

        if result:
            logger.info("Webhook subscription verified successfully")
            return result, 200
        else:
            logger.warning("Webhook verification failed")
            return "Verification failed", 403

    else:  # POST
        # Handle incoming webhook events
        if not meta_service:
            logger.error("MetaService not configured")
            return jsonify({"error": "Service not configured"}), 500

        if not app_secret:
            logger.error("App secret not configured - cannot verify webhooks")
            return jsonify({"error": "Service misconfigured"}), 500

        return handle_webhook_event(request, meta_service, app_secret)


@webhook_bp.route("/webhook/debug", methods=["POST"])
def webhook_debug():
    """
    Debug endpoint to manually verify signature calculation.
    
    POST with JSON body:
    {
        "payload": "<raw json string>",
        "signature": "sha256=...",
        "app_secret": "<your app secret>"  # optional, uses env if not provided
    }
    """
    from flask import current_app
    import hmac
    import hashlib
    
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    
    payload_str = data.get("payload", "")
    signature = data.get("signature", "")
    app_secret = data.get("app_secret") or current_app.config.get("META_APP_SECRET")
    
    if not payload_str or not signature or not app_secret:
        return jsonify({"error": "payload, signature, and app_secret required"}), 400
    
    # Calculate signature
    payload_bytes = payload_str.encode('utf-8')
    computed = hmac.new(
        app_secret.encode('utf-8'),
        payload_bytes,
        hashlib.sha256
    ).hexdigest()
    
    expected_hash = signature.split("=", 1)[1] if "=" in signature else signature
    
    return jsonify({
        "app_secret_preview": app_secret[:4] + "...",
        "payload_length": len(payload_str),
        "signature_received": signature,
        "hash_expected": expected_hash,
        "hash_computed": computed,
        "match": hmac.compare_digest(computed.lower(), expected_hash.lower()),
        "curl_command": f"echo -n '{payload_str}' | openssl dgst -sha256 -hmac '{app_secret}'"
    })


def handle_webhook_event(request, meta_service: MetaService, app_secret: str):
    """
    Process incoming webhook events from Instagram.
    """
    # Verify webhook signature for security
    signature = request.headers.get("X-Hub-Signature-256", "")
    
    # CRITICAL: Get raw payload BEFORE any parsing
    # Flask's request.get_data() caches the data, so we can still parse JSON later
    payload = request.get_data(cache=True, as_text=False)
    
    # Also get as text for logging
    payload_text = request.get_data(cache=True, as_text=True)

    # Debug: Log incoming request details
    logger.info(f"Webhook POST received:")
    logger.info(f"  - X-Hub-Signature-256: {signature}")
    logger.info(f"  - Content-Type: {request.headers.get('Content-Type', 'MISSING')}")
    logger.info(f"  - Content-Length: {request.headers.get('Content-Length', 'MISSING')}")
    logger.info(f"  - Payload bytes length: {len(payload)}")
    logger.info(f"  - Payload text length: {len(payload_text)}")
    logger.info(f"  - Full payload: {payload_text}")
    logger.info(f"  - Raw bytes (hex): {payload[:100].hex()}")

    # Verify signature
    signature_valid = meta_service.verify_webhook_signature(
        payload, signature, app_secret
    )

    if not signature_valid:
        logger.error("Invalid webhook signature - rejecting request")
        # Log verification details for manual debugging
        logger.error(f"Manual verification - App Secret (first 4 chars): {app_secret[:4] if app_secret else 'NONE'}...")
        logger.error(f"Manual verification - Payload: {payload_text}")
        logger.error(f"Manual verification - Expected signature: {signature}")
        return jsonify({"error": "Invalid signature"}), 401

    # Parse JSON payload
    try:
        data = request.get_json(force=True)
    except Exception as e:
        logger.error(f"Failed to parse webhook payload: {e}")
        return jsonify({"error": "Invalid JSON"}), 400

    if not data:
        logger.error("Empty webhook payload")
        return jsonify({"error": "Empty payload"}), 400

    # Verify this is an Instagram event
    if data.get("object") != "instagram":
        logger.warning(f"Received non-Instagram webhook: {data.get('object')}")
        return jsonify({"status": "ignored"}), 200

    entries = data.get("entry", [])
    processed_count = 0
    error_count = 0

    for entry in entries:
        instagram_business_id = entry.get("id")

        if not instagram_business_id:
            logger.warning("Webhook entry missing ID")
            continue

        # Find the account in our database
        account = InstagramAccount.query.filter_by(
            instagram_business_account_id=instagram_business_id
        ).first()

        if not account:
            logger.warning(
                f"Received webhook for unknown account: {instagram_business_id}"
            )
            continue

        # Update last used timestamp
        account.last_used_at = datetime.utcnow()

        # Process changes (comments, mentions, etc.)
        changes = entry.get("changes", [])
        for change in changes:
            try:
                process_change(change, account, meta_service)
                processed_count += 1
            except Exception as e:
                logger.exception(f"Error processing change: {e}")
                error_count += 1

        # Process messaging events (if any)
        messaging_events = entry.get("messaging", [])
        for messaging in messaging_events:
            try:
                process_messaging_event(messaging, account, meta_service)
            except Exception as e:
                logger.exception(f"Error processing messaging event: {e}")
                error_count += 1

    # Commit all database changes
    try:
        db.session.commit()
    except Exception as e:
        logger.exception(f"Database commit failed: {e}")
        db.session.rollback()
        return jsonify({"error": "Database error"}), 500

    logger.info(f"Processed {processed_count} events, {error_count} errors")
    return (
        jsonify(
            {"status": "processed", "processed": processed_count, "errors": error_count}
        ),
        200,
    )


def process_change(change: dict, account: InstagramAccount, meta_service: MetaService):
    """
    Process a single change event (comment, mention, etc.)
    """
    field = change.get("field")
    value = change.get("value", {})

    if not field:
        logger.warning("Change event missing field type")
        return

    logger.info(
        f"Processing {field} event for account {account.instagram_username or account.id}"
    )

    # Generate a unique event ID from the change data
    event_id_parts = [
        field,
        value.get("media_id", ""),
        value.get("comment_id", ""),
        str(value.get("t", "")),
    ]
    event_id = "_".join(filter(None, event_id_parts))

    if not event_id or event_id == field:
        # Use timestamp-based ID if no unique parts available
        event_id = f"{field}_{account.id}_{datetime.utcnow().timestamp()}"

    # Check if we already processed this event (idempotency)
    existing = WebhookEvent.query.filter_by(event_id=event_id).first()
    if existing:
        logger.debug(f"Event {event_id} already processed, skipping")
        return

    # Extract sender info
    from_data = value.get("from", {})
    if isinstance(from_data, dict):
        sender_id = from_data.get("id")
        sender_username = from_data.get("username")
    else:
        sender_id = value.get("from_id")
        sender_username = value.get("from_username")

    # Create webhook event record
    webhook_event = WebhookEvent(
        event_id=event_id,
        event_type=field,
        media_id=value.get("media_id"),
        media_type=value.get("media_type"),
        comment_id=value.get("comment_id"),
        comment_text=value.get("text") or value.get("comment_text"),
        sender_id=sender_id,
        sender_username=sender_username,
        raw_payload=json.dumps(value, default=str),
    )

    db.session.add(webhook_event)

    try:
        db.session.flush()  # Get the ID without committing
    except Exception as e:
        logger.error(f"Failed to save webhook event: {e}")
        db.session.rollback()
        return

    # Process based on event type
    try:
        if field == "mentions":
            handle_mention(webhook_event, account, meta_service)
        elif field == "comments":
            handle_comment(webhook_event, account, meta_service)
        else:
            logger.info(f"Unhandled event type: {field}")

        webhook_event.processed = True
        webhook_event.processed_at = datetime.utcnow()

    except Exception as e:
        logger.exception(f"Error handling {field} event: {e}")
        webhook_event.error_message = str(e)[:500]  # Limit error message length


def handle_mention(
    event: WebhookEvent, account: InstagramAccount, meta_service: MetaService
):
    """
    Handle a mention event (someone @mentioned the account in a comment/story).
    """
    logger.info(
        f"Handling mention from {event.sender_username} on media {event.media_id}"
    )

    # For mentions, we can only reply if we have a comment_id
    if event.comment_id:
        send_auto_reply_to_comment(event, account, meta_service)
    else:
        logger.info(
            f"Story mention received from {event.sender_username} - no auto-reply sent"
        )


def handle_comment(
    event: WebhookEvent, account: InstagramAccount, meta_service: MetaService
):
    """
    Handle a comment event (someone commented on the account's post).
    """
    logger.info(
        f"Handling comment from {event.sender_username} on media {event.media_id}"
    )
    send_auto_reply_to_comment(event, account, meta_service)


def send_auto_reply_to_comment(
    event: WebhookEvent, account: InstagramAccount, meta_service: MetaService
):
    """
    Send an auto-reply to a comment.
    """
    if not event.comment_id:
        logger.warning("No comment ID available for reply")
        event.error_message = "No comment ID"
        return

    # Get token from secure store
    token_store = get_store()
    if not token_store:
        logger.error("Token store not available")
        event.error_message = "Token store not available"
        return

    access_token = token_store.retrieve(account.id, account.access_token_encrypted)

    if not access_token:
        logger.error(f"No access token available for account {account.id}")
        event.error_message = "Access token not available"
        return

    # Truncate message if needed
    message = truncate_message(AUTO_REPLY_MESSAGE)

    try:
        # Send the reply
        result = meta_service.reply_to_comment(
            comment_id=event.comment_id, message=message, access_token=access_token
        )

        # Log the auto-reply
        reply_log = AutoReplyLog(
            webhook_event_id=event.id,
            recipient_id=event.sender_id or "unknown",
            recipient_username=event.sender_username,
            message_text=message,
            message_id=result.get("id"),
            success=True,
        )

        db.session.add(reply_log)

        event.auto_reply_sent = True
        event.auto_reply_message_id = result.get("id")

        logger.info(f"Auto-reply sent successfully: {result.get('id')}")

    except MetaAPIError as e:
        logger.error(f"Failed to send auto-reply: {e}")

        reply_log = AutoReplyLog(
            webhook_event_id=event.id,
            recipient_id=event.sender_id or "unknown",
            recipient_username=event.sender_username,
            message_text=message,
            success=False,
            error_message=str(e)[:500],
        )

        db.session.add(reply_log)
        event.error_message = f"Auto-reply failed: {str(e)}"[:500]


def process_messaging_event(
    messaging: dict, account: InstagramAccount, meta_service: MetaService
):
    """
    Process a messaging event (DM received).

    Structure:
    {
        "sender": {"id": "<PSID>"},
        "recipient": {"id": "<PAGE_ID>"},
        "timestamp": 1234567890,
        "message": {"mid": "...", "text": "Hello"}
    }
    """
    sender = messaging.get("sender", {})
    message = messaging.get("message", {})

    sender_id = sender.get("id")
    message_text = message.get("text")

    if not sender_id:
        logger.warning("Messaging event missing sender ID")
        return

    logger.info(
        f"Received DM from {sender_id}: {message_text[:100] if message_text else '(no text)'}"
    )

    # DM auto-reply not implemented - log only


@webhook_bp.route("/webhook/health", methods=["GET"])
def webhook_health():
    """Health check endpoint for webhook status."""
    try:
        # Get counts for monitoring
        total_events = WebhookEvent.query.count()
        processed_events = WebhookEvent.query.filter_by(processed=True).count()
        failed_events = WebhookEvent.query.filter(
            WebhookEvent.error_message.isnot(None)
        ).count()

        # Get recent events (last 24 hours)
        from datetime import timedelta

        recent_cutoff = datetime.utcnow() - timedelta(hours=24)
        recent_events = (
            WebhookEvent.query.filter(WebhookEvent.created_at >= recent_cutoff)
            .order_by(WebhookEvent.created_at.desc())
            .limit(10)
            .all()
        )

        return (
            jsonify(
                {
                    "status": "healthy",
                    "stats": {
                        "total_events": total_events,
                        "processed_events": processed_events,
                        "failed_events": failed_events,
                        "success_rate": (
                            round((processed_events / total_events * 100), 2)
                            if total_events > 0
                            else 0
                        ),
                    },
                    "recent_events": [event.to_dict() for event in recent_events],
                }
            ),
            200,
        )

    except Exception as e:
        logger.exception(f"Health check failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
