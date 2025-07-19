#!/usr/bin/env python3
"""
Direct SMTP test using the same settings as production
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Production SMTP settings from your Railway environment
SMTP_SERVER = "smtp.office365.com"
SMTP_PORT = 587
SMTP_USER = "cruz@atomiktrading.io"
SMTP_PASSWORD = "Corona88."
SMTP_FROM_EMAIL = "support@atomiktrading.io"
TO_EMAIL = "cruzh5150@gmail.com"

def test_smtp_direct():
    """Test SMTP connection directly"""
    print("🔧 Testing direct SMTP connection...")
    print(f"Server: {SMTP_SERVER}:{SMTP_PORT}")
    print(f"User: {SMTP_USER}")
    print(f"From: {SMTP_FROM_EMAIL}")
    print(f"To: {TO_EMAIL}")
    
    try:
        # Create message
        message = MIMEMultipart()
        message["Subject"] = "SMTP Test from Atomik Trading"
        message["From"] = SMTP_FROM_EMAIL
        message["To"] = TO_EMAIL
        
        # Add body
        body = """
        <h2>SMTP Test</h2>
        <p>This is a test email to verify SMTP configuration.</p>
        <p>If you receive this, email sending is working correctly.</p>
        """
        message.attach(MIMEText(body, "html"))
        
        # Connect and send
        print("📡 Connecting to SMTP server...")
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            print("🔒 Starting TLS...")
            server.starttls()
            
            print("🔐 Logging in...")
            server.login(SMTP_USER, SMTP_PASSWORD)
            
            print("📤 Sending email...")
            server.sendmail(SMTP_FROM_EMAIL, TO_EMAIL, message.as_string())
            
        print("✅ Email sent successfully!")
        print("📬 Check your inbox at cruzh5150@gmail.com")
        return True
        
    except smtplib.SMTPAuthenticationError as e:
        print(f"❌ Authentication failed: {e}")
        print("💡 Possible solutions:")
        print("   - Check if 2FA is enabled (need app password)")
        print("   - Verify SMTP is enabled in Office 365")
        print("   - Try using the main account password")
        return False
        
    except smtplib.SMTPConnectError as e:
        print(f"❌ Connection failed: {e}")
        print("💡 Check server and port settings")
        return False
        
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

if __name__ == "__main__":
    print("📧 Direct SMTP Test")
    print("=" * 50)
    test_smtp_direct()
    print("=" * 50)