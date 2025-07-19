#!/usr/bin/env python3
"""
Debug email sending by testing each component individually
"""
import sys
import os
sys.path.append('.')

import asyncio
from app.services.email.email_notification import PaymentEmailService, send_email

async def test_direct_email_service():
    """Test the PaymentEmailService directly"""
    print("🧪 Testing PaymentEmailService.send_payment_failure_email...")
    
    try:
        result = await PaymentEmailService.send_payment_failure_email(
            user_email="cruzh5150@gmail.com",
            user_name="Cruz",
            failure_reason="Test payment failure",
            days_in_grace=7,
            billing_portal_url="https://atomiktrading.io/billing"
        )
        
        if result:
            print("✅ PaymentEmailService succeeded")
        else:
            print("❌ PaymentEmailService failed")
        
        return result
        
    except Exception as e:
        print(f"❌ Exception in PaymentEmailService: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_base_send_email():
    """Test the base send_email function directly"""
    print("\n🧪 Testing base send_email function...")
    
    try:
        context = {
            "user_name": "Cruz",
            "failure_reason": "Test payment failure",
            "days_in_grace": 7,
            "billing_portal_url": "https://atomiktrading.io/billing",
            "support_email": "support@atomiktrading.io",
            "company_name": "Atomik Trading"
        }
        
        result = await send_email(
            to="cruzh5150@gmail.com",
            subject="Test Payment Failed - Action Required",
            template="payment_failure",
            context=context
        )
        
        if result:
            print("✅ Base send_email succeeded")
        else:
            print("❌ Base send_email failed")
        
        return result
        
    except Exception as e:
        print(f"❌ Exception in base send_email: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_template_loading():
    """Test if template can be loaded"""
    print("\n🧪 Testing template loading...")
    
    try:
        from jinja2 import Environment, FileSystemLoader
        import os
        
        # Use same path as email service
        templates_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
        print(f"Templates directory: {templates_dir}")
        
        env = Environment(loader=FileSystemLoader(templates_dir))
        
        template_path = "emails/payment_failure.html"
        template_obj = env.get_template(template_path)
        
        # Test rendering
        context = {
            "user_name": "Test User",
            "failure_reason": "Test reason",
            "days_in_grace": 7,
            "billing_portal_url": "https://example.com",
            "support_email": "support@example.com",
            "company_name": "Test Company"
        }
        
        html_content = template_obj.render(**context)
        print(f"✅ Template loaded and rendered successfully")
        print(f"📄 Content length: {len(html_content)} characters")
        
        return True
        
    except Exception as e:
        print(f"❌ Template loading failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Run all email tests"""
    print("🔍 Email Service Debug Tests")
    print("=" * 50)
    
    # Test 1: Template loading
    template_ok = test_template_loading()
    
    # Test 2: Base email function
    if template_ok:
        email_ok = await test_base_send_email()
    else:
        email_ok = False
    
    # Test 3: Payment service
    if email_ok:
        service_ok = await test_direct_email_service()
    else:
        service_ok = False
    
    print("\n" + "=" * 50)
    print("📊 Test Results:")
    print(f"Template Loading: {'✅' if template_ok else '❌'}")
    print(f"Base Email Function: {'✅' if email_ok else '❌'}")
    print(f"Payment Email Service: {'✅' if service_ok else '❌'}")
    
    if service_ok:
        print("\n🎉 All tests passed! Check your email.")
    else:
        print("\n💥 Some tests failed. Check the errors above.")

if __name__ == "__main__":
    asyncio.run(main())