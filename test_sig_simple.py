#!/usr/bin/env python3
"""Simple signature test - hardcoded values from logs."""

import hmac
import hashlib
import os

# From logs
PAYLOAD = '{"entry": [{"id": "17841446380066229", "time": 1772084651, "changes": [{"value": {"from": {"id": "25878337938514402", "username": "nritya.aashini"}, "media": {"id": "17960714109048735", "media_product_type": "FEED"}, "id": "18056672741419154", "text": "Wow"}, "field": "comments"}]}], "object": "instagram"}'

EXPECTED_HASH = '4097fe3b4ea61e2affec1c8494fb8a0d6de23ad3ea5012a4bff2d41bff761622'

# Get secret from env
secret = os.environ.get('META_APP_SECRET', '')

print("=" * 60)
print("Webhook Signature Test")
print("=" * 60)

if not secret:
    print("ERROR: META_APP_SECRET not set!")
    exit(1)

print(f"\nApp Secret (first 4 chars): {secret[:4]}...")
print(f"App Secret length: {len(secret)}")

# Calculate
computed = hmac.new(
    secret.encode('utf-8'),
    PAYLOAD.encode('utf-8'),
    hashlib.sha256
).hexdigest()

print(f"\nExpected: {EXPECTED_HASH}")
print(f"Computed: {computed}")
print(f"Match: {hmac.compare_digest(computed, EXPECTED_HASH)}")

# Also try with secret from input
print("\n" + "=" * 60)
test_secret = input("Enter app secret to test (or press Enter to skip): ").strip()
if test_secret:
    computed2 = hmac.new(
        test_secret.encode('utf-8'),
        PAYLOAD.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    print(f"\nWith provided secret:")
    print(f"  Secret (first 4 chars): {test_secret[:4]}...")
    print(f"  Computed: {computed2}")
    print(f"  Expected: {EXPECTED_HASH}")
    print(f"  Match: {hmac.compare_digest(computed2, EXPECTED_HASH)}")
