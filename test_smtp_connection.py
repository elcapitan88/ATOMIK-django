#!/usr/bin/env python3
"""
Test SMTP connection and email sending
"""
import requests
import json

API_BASE_URL = "https://api.atomiktrading.io"

def test_smtp_connection():
    """Test SMTP connection by calling the admin email test endpoint"""
    print("🔍 Testing SMTP connection...")
    
    try:
        # Call the admin test email endpoint
        response = requests.post(
            f"{API_BASE_URL}/api/v1/admin/test-email",
            json={
                "email": "cruzh5150@gmail.com",
                "username": "Cruz"
            }
        )
        
        if response.status_code == 200:
            print("✅ SMTP test email sent successfully")
            print("📬 Check your email at cruzh5150@gmail.com")
            return True
        else:
            print(f"❌ SMTP test failed: {response.status_code}")
            print(f"Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Error testing SMTP: {e}")
        return False

def check_email_logs():
    """Check recent email sending logs"""
    print("\n📋 To check email logs in Railway:")
    print("1. Go to Railway dashboard")
    print("2. Open your backend service")
    print("3. Go to 'Logs' tab")
    print("4. Search for 'Failed to send email' or 'Email sent successfully'")
    print("5. Look for any SMTP connection errors")

if __name__ == "__main__":
    print("📧 SMTP Connection Test")
    print("=" * 40)
    
    success = test_smtp_connection()
    
    if not success:
        check_email_logs()
        print("\n🔧 Potential fixes:")
        print("1. Check if SMTP credentials are correct")
        print("2. Verify Office 365 allows SMTP access")
        print("3. Check if 2FA is enabled (may need app password)")
        print("4. Test with Gmail SMTP as alternative")
    
    print("\n" + "=" * 40)