#!/usr/bin/env python3
"""
Test script for payment failure handling in production
This simulates Stripe webhook events to test the payment failure flow
"""

import requests
import json
import time
import hmac
import hashlib
from datetime import datetime

# Configuration - Update these for your production environment
API_BASE_URL = "https://api.atomiktrading.io"  # Your production API URL
WEBHOOK_ENDPOINT = f"{API_BASE_URL}/api/v1/subscriptions/webhook"
WEBHOOK_SECRET = "whsec_752dec8101abcf39a680538618710f8a91bbdceb0dfcccdeed6d15f3c49e4ab9"  # From your .env

# Test configuration
TEST_CUSTOMER_ID = "cus_TEST123"  # Replace with a real test customer ID
TEST_INVOICE_ID = "in_TEST123"
TEST_SUBSCRIPTION_ID = "sub_TEST123"

def generate_stripe_signature(payload: str, secret: str) -> str:
    """Generate Stripe webhook signature"""
    timestamp = int(time.time())
    signed_payload = f"{timestamp}.{payload}"
    signature = hmac.new(
        secret.encode('utf-8'),
        signed_payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v1={signature}"

def send_webhook_event(event_type: str, data: dict) -> requests.Response:
    """Send a webhook event to the API"""
    event = {
        "id": f"evt_test_{int(time.time())}",
        "object": "event",
        "api_version": "2023-10-16",
        "created": int(time.time()),
        "data": {
            "object": data
        },
        "livemode": False,
        "pending_webhooks": 1,
        "request": {
            "id": None,
            "idempotency_key": None
        },
        "type": event_type
    }
    
    payload = json.dumps(event)
    signature = generate_stripe_signature(payload, WEBHOOK_SECRET.replace("whsec_", ""))
    
    headers = {
        "Content-Type": "application/json",
        "Stripe-Signature": signature
    }
    
    return requests.post(WEBHOOK_ENDPOINT, data=payload, headers=headers)

def test_payment_failure():
    """Test payment failure webhook"""
    print("🔴 Testing payment failure webhook...")
    
    invoice_data = {
        "id": TEST_INVOICE_ID,
        "object": "invoice",
        "customer": TEST_CUSTOMER_ID,
        "subscription": TEST_SUBSCRIPTION_ID,
        "status": "open",
        "amount_due": 19900,  # $199.00
        "currency": "usd",
        "last_payment_error": {
            "message": "Your card was declined.",
            "type": "card_error",
            "code": "card_declined"
        }
    }
    
    response = send_webhook_event("invoice.payment_failed", invoice_data)
    print(f"Response: {response.status_code} - {response.json()}")
    return response.status_code == 200

def test_payment_success():
    """Test payment success webhook (recovery)"""
    print("\n🟢 Testing payment success webhook (recovery)...")
    
    invoice_data = {
        "id": TEST_INVOICE_ID,
        "object": "invoice",
        "customer": TEST_CUSTOMER_ID,
        "subscription": TEST_SUBSCRIPTION_ID,
        "status": "paid",
        "amount_paid": 19900,  # $199.00
        "currency": "usd"
    }
    
    response = send_webhook_event("invoice.payment_succeeded", invoice_data)
    print(f"Response: {response.status_code} - {response.json()}")
    return response.status_code == 200

def check_payment_status(user_token: str):
    """Check payment status for a user"""
    print("\n📊 Checking payment status...")
    
    headers = {
        "Authorization": f"Bearer {user_token}"
    }
    
    response = requests.get(f"{API_BASE_URL}/api/v1/subscriptions/payment-status", headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        print(f"Payment Status: {json.dumps(data, indent=2)}")
        return data
    else:
        print(f"Error: {response.status_code} - {response.text}")
        return None

def create_billing_portal_session(user_token: str):
    """Create billing portal session"""
    print("\n💳 Creating billing portal session...")
    
    headers = {
        "Authorization": f"Bearer {user_token}"
    }
    
    response = requests.post(f"{API_BASE_URL}/api/v1/subscriptions/create-billing-portal-session", headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        print(f"Billing Portal URL: {data.get('url')}")
        return data.get('url')
    else:
        print(f"Error: {response.status_code} - {response.text}")
        return None

def main():
    """Run all tests"""
    print("🧪 Payment Failure Testing Script")
    print("=" * 50)
    
    # Note: You'll need to get these from your production environment
    print("\n⚠️  Before running tests:")
    print("1. Update TEST_CUSTOMER_ID with a real Stripe customer ID")
    print("2. Get a valid user token for API authentication")
    print("3. Ensure webhook endpoint is accessible")
    
    # Uncomment and update these when ready to test
    # USER_TOKEN = "your_jwt_token_here"
    
    # Test 1: Payment Failure
    # if test_payment_failure():
    #     print("✅ Payment failure webhook test passed")
    # else:
    #     print("❌ Payment failure webhook test failed")
    
    # Test 2: Check Payment Status
    # status = check_payment_status(USER_TOKEN)
    
    # Test 3: Create Billing Portal
    # portal_url = create_billing_portal_session(USER_TOKEN)
    
    # Test 4: Payment Recovery
    # if test_payment_success():
    #     print("✅ Payment recovery webhook test passed")
    # else:
    #     print("❌ Payment recovery webhook test failed")
    
    print("\n" + "=" * 50)
    print("Testing complete!")

if __name__ == "__main__":
    main()