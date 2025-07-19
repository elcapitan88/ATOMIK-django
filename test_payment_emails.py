#!/usr/bin/env python3
"""
Direct API test for payment failure emails
Tests the email system by triggering payment failure for cruzh5150@gmail.com
"""

import requests
import json
import sys

# Production API configuration
API_BASE_URL = "https://api.atomiktrading.io"
TEST_EMAIL = "cruzh5150@gmail.com"

def get_user_token(email: str, password: str) -> str:
    """Login and get JWT token"""
    print(f"🔐 Logging in as {email}...")
    
    response = requests.post(
        f"{API_BASE_URL}/api/v1/auth/login",
        data={"username": email, "password": password}
    )
    
    if response.status_code == 200:
        data = response.json()
        print("✅ Login successful")
        return data.get("access_token")
    else:
        print(f"❌ Login failed: {response.status_code} - {response.text}")
        return None

def test_email_directly(token: str):
    """Test email sending directly through a test endpoint"""
    print("\n📧 Testing email system...")
    
    # This endpoint would need to be created for testing
    headers = {"Authorization": f"Bearer {token}"}
    
    # First, let's check the payment status
    response = requests.get(
        f"{API_BASE_URL}/api/v1/subscriptions/payment-status",
        headers=headers
    )
    
    if response.status_code == 200:
        status = response.json()
        print(f"Current payment status: {json.dumps(status, indent=2)}")
        return status
    else:
        print(f"❌ Failed to get payment status: {response.status_code}")
        return None

def trigger_test_payment_failure(token: str):
    """Create a test endpoint to manually trigger payment failure"""
    print("\n🔴 Triggering test payment failure...")
    
    # This is a test endpoint you would need to create
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.post(
        f"{API_BASE_URL}/api/v1/subscriptions/test-payment-failure",
        headers=headers,
        json={
            "send_email": True,
            "failure_reason": "Test payment failure for email verification"
        }
    )
    
    if response.status_code == 200:
        print("✅ Test payment failure triggered")
        print("📬 Check your email at cruzh5150@gmail.com")
        return True
    else:
        print(f"❌ Failed to trigger test: {response.status_code} - {response.text}")
        return False

def main():
    """Run email tests"""
    print("🧪 Payment Failure Email Test")
    print("=" * 50)
    
    # You'll need to provide the password
    password = input("Enter password for cruzh5150@gmail.com: ")
    
    # Get authentication token
    token = get_user_token(TEST_EMAIL, password)
    if not token:
        print("❌ Failed to authenticate. Exiting.")
        sys.exit(1)
    
    # Check current payment status
    status = test_email_directly(token)
    
    # Ask if user wants to trigger test email
    if status:
        trigger = input("\n⚠️  Would you like to trigger a test payment failure email? (y/n): ")
        if trigger.lower() == 'y':
            trigger_test_payment_failure(token)
    
    print("\n" + "=" * 50)
    print("Testing complete!")

if __name__ == "__main__":
    main()