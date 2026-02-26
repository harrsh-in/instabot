#!/usr/bin/env python3
"""
Test script to verify webhook signature calculation.

Usage:
    python test_signature.py

This will help debug why the signature doesn't match.
"""

import hmac
import hashlib
import os
from dotenv import load_dotenv

# Load from .env file
load_dotenv()

# The exact payload from the logs
PAYLOAD = '{"entry": [{"id": "17841446380066229", "time": 1772084651, "changes": [{"value": {"from": {"id": "25878337938514402", "username": "nritya.aashini"}, "media": {"id": "17960714109048735", "media_product_type": "FEED"}, "id": "18056672741419154", "text": "Wow"}, "field": "comments"}]}], "object": "instagram"}'

# The expected signature from Meta
EXPECTED_SIGNATURE = 'sha256=4097fe3b4ea61e2affec1c8494fb8a0d6de23ad3ea5012a4bff2d41bff761622'
EXPECTED_HASH = EXPECTED_SIGNATURE.split('=', 1)[1]

# Get app secret from environment
APP_SECRET = os.environ.get('META_APP_SECRET', '')

def test_signature(secret: str, description: str):
    """Test signature calculation with given secret."""
    if not secret:
        print(f"❌ {description}: Secret is empty")
        return False
    
    computed = hmac.new(
        secret.encode('utf-8'),
        PAYLOAD.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    match = hmac.compare_digest(computed.lower(), EXPECTED_HASH.lower())
    
    print(f"\n{'✅' if match else '❌'} {description}")
    print(f"   Secret (first 4 chars): {secret[:4]}...")
    print(f"   Secret length: {len(secret)}")
    print(f"   Computed: {computed}")
    print(f"   Expected: {EXPECTED_HASH}")
    print(f"   Match: {match}")
    
    return match

def main():
    print("=" * 70)
    print("Webhook Signature Verification Test")
    print("=" * 70)
    
    print(f"\nPayload ({len(PAYLOAD)} chars):")
    print(PAYLOAD)
    
    print(f"\nExpected signature: {EXPECTED_SIGNATURE}")
    
    # Test 1: Current env secret
    if APP_SECRET:
        test_signature(APP_SECRET, "From .env file (META_APP_SECRET)")
    else:
        print("\n❌ META_APP_SECRET not found in .env file")
    
    # Test 2: Try common variations
    print("\n" + "=" * 70)
    print("Testing common issues...")
    print("=" * 70)
    
    if APP_SECRET:
        # Try with trailing newline
        test_signature(APP_SECRET + '\n', "With trailing newline")
        
        # Try with trailing space
        test_signature(APP_SECRET + ' ', "With trailing space")
        
        # Try with quotes
        test_signature(APP_SECRET.strip('"\''), "With quotes stripped")
    
    print("\n" + "=" * 70)
    print("Manual Test Instructions:")
    print("=" * 70)
    print("""
To verify manually with OpenSSL:

1. Save payload to file:
   cat > /tmp/payload.json << 'EOF'
{"entry": [{"id": "17841446380066229", "time": 1772084651, "changes": [{"value": {"from": {"id": "25878337938514402", "username": "nritya.aashini"}, "media": {"id": "17960714109048735", "media_product_type": "FEED"}, "id": "18056672741419154", "text": "Wow"}, "field": "comments"}]}], "object": "instagram"}
EOF

2. Calculate HMAC-SHA256:
   openssl dgst -sha256 -hmac "YOUR_APP_SECRET" /tmp/payload.json

3. Compare with expected:
   Expected: 4097fe3b4ea61e2affec1c8494fb8a0d6de23ad3ea5012a4bff2d41bff761622

To test with a different secret, edit this script or set META_APP_SECRET env var.
""")
    
    # Interactive test
    print("\n" + "=" * 70)
    secret_input = input("Enter app secret to test (or press Enter to skip): ").strip()
    if secret_input:
        test_signature(secret_input, "User provided secret")

if __name__ == "__main__":
    main()
