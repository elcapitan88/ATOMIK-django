# app/services/email_service.py

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, Optional
from jinja2 import Environment, PackageLoader, select_autoescape
from ...core.config import settings

# Configure logging
logger = logging.getLogger(__name__)

# Set up Jinja2 for template rendering
try:
    env = Environment(
        loader=PackageLoader('app', 'templates/emails'),
        autoescape=select_autoescape(['html', 'xml'])
    )
except Exception as e:
    logger.error(f"Failed to initialize email templates: {str(e)}")
    env = None

async def send_email(
    to: str,
    subject: str,
    template: str,
    context: Dict[str, Any]
) -> bool:
    """
    Send an email using the configured SMTP server.
    
    Args:
        to: Recipient email address
        subject: Email subject
        template: Name of the template to use (without extension)
        context: Dictionary of variables to pass to the template
        
    Returns:
        bool: Success status
    """
    # Check for SMTP configuration
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.warning("SMTP not configured. Email not sent.")
        logger.info(f"Would have sent email to: {to}, subject: {subject}, template: {template}")
        return False
    
    try:
        # Create message
        message = MIMEMultipart('alternative')
        message['Subject'] = subject
        
        # Use from_email alias if configured, otherwise use SMTP_USER
        from_email = getattr(settings, 'SMTP_FROM_EMAIL', settings.SMTP_USER)
        message['From'] = from_email
        message['To'] = to
        
        # Render template if environment is configured
        if env:
            # Try to load and render the template
            try:
                template_obj = env.get_template(f"{template}.html")
                html_content = template_obj.render(**context)
                
                # Add HTML content
                html_part = MIMEText(html_content, 'html')
                message.attach(html_part)
                
            except Exception as template_error:
                logger.error(f"Failed to render email template: {str(template_error)}")
                # Fallback to plain text
                text = f"Subject: {subject}\n\n"
                for key, value in context.items():
                    text += f"{key}: {value}\n"
                text_part = MIMEText(text, 'plain')
                message.attach(text_part)
        else:
            # Fallback to plain text if no template environment
            text = f"Subject: {subject}\n\n"
            for key, value in context.items():
                text += f"{key}: {value}\n"
            text_part = MIMEText(text, 'plain')
            message.attach(text_part)
        
        # Send the email
        with smtplib.SMTP('smtp.office365.com', 587) as server:
            server.starttls()  # Office 365 requires TLS
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(from_email, to, message.as_string())
            
        logger.info(f"Email sent successfully to {to}: {subject}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send email: {str(e)}")
        return False

# Template for password reset email
PASSWORD_RESET_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Reset Your Password</title>
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background-color: #00C6E0; padding: 20px; color: white; text-align: center; }
        .content { padding: 20px; background-color: #f9f9f9; border: 1px solid #eee; }
        .button { display: inline-block; padding: 10px 20px; background-color: #00C6E0; color: white; 
                 text-decoration: none; border-radius: 4px; margin: 20px 0; }
        .footer { margin-top: 20px; font-size: 12px; color: #777; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Reset Your Password</h1>
        </div>
        <div class="content">
            <p>Hello {{ username }},</p>
            <p>We received a request to reset your password. If you didn't make this request, you can safely ignore this email.</p>
            <p>To reset your password, click the button below:</p>
            <p style="text-align: center;">
                <a href="{{ reset_url }}" class="button">Reset Password</a>
            </p>
            <p>Or copy and paste this link into your browser:</p>
            <p style="word-break: break-all;">{{ reset_url }}</p>
            <p>This link will expire in {{ expiry_hours }} hour(s).</p>
            <p>Best regards,<br>The Atomik Trading Team</p>
        </div>
        <div class="footer">
            <p>If you need any assistance, please contact us at support@atomiktrading.io</p>
        </div>
    </div>
</body>
</html>
"""

# Create templates directory and save the template
import os
import pathlib

def setup_email_templates():
    """Create template directories and save default templates"""
    try:
        # Create template directories
        templates_dir = pathlib.Path('app/templates/emails')
        templates_dir.mkdir(parents=True, exist_ok=True)
        
        # Save password reset template
        with open(templates_dir / 'password_reset.html', 'w') as f:
            f.write(PASSWORD_RESET_TEMPLATE)
            
        logger.info("Email templates set up successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to set up email templates: {str(e)}")
        return False

# Run setup on import if in development mode
if settings.ENVIRONMENT == 'development':
    setup_email_templates()