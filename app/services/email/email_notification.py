# app/services/email/email_notification.py
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Dict, Any, Optional

from fastapi import BackgroundTasks
from jinja2 import Environment, FileSystemLoader
import os

from app.core.config import settings

logger = logging.getLogger(__name__)

class PaymentEmailService:
    """Service for sending payment-related emails"""
    
    @staticmethod
    async def send_payment_failure_email(
        user_email: str,
        user_name: str = None,
        failure_reason: str = None,
        days_in_grace: int = 7,
        billing_portal_url: str = None
    ) -> bool:
        """Send payment failure notification email"""
        try:
            context = {
                "user_name": user_name or user_email.split("@")[0],
                "failure_reason": failure_reason or "Your payment could not be processed",
                "days_in_grace": days_in_grace,
                "billing_portal_url": billing_portal_url,
                "support_email": "support@atomiktrading.io",
                "company_name": "Atomik Trading"
            }
            
            return await send_email(
                to=user_email,
                subject="Payment Failed - Action Required",
                template="payment_failure",
                context=context
            )
        except Exception as e:
            logger.error(f"Failed to send payment failure email to {user_email}: {str(e)}")
            return False
    
    @staticmethod
    async def send_grace_period_reminder(
        user_email: str,
        user_name: str = None,
        days_remaining: int = 3,
        billing_portal_url: str = None
    ) -> bool:
        """Send grace period reminder email"""
        try:
            context = {
                "user_name": user_name or user_email.split("@")[0],
                "days_remaining": days_remaining,
                "billing_portal_url": billing_portal_url,
                "support_email": "support@atomiktrading.io",
                "company_name": "Atomik Trading"
            }
            
            return await send_email(
                to=user_email,
                subject=f"Payment Reminder - {days_remaining} Days Remaining",
                template="grace_period_reminder",
                context=context
            )
        except Exception as e:
            logger.error(f"Failed to send grace period reminder to {user_email}: {str(e)}")
            return False
    
    @staticmethod
    async def send_final_notice(
        user_email: str,
        user_name: str = None,
        billing_portal_url: str = None
    ) -> bool:
        """Send final notice before suspension"""
        try:
            context = {
                "user_name": user_name or user_email.split("@")[0],
                "billing_portal_url": billing_portal_url,
                "support_email": "support@atomiktrading.io",
                "company_name": "Atomik Trading"
            }
            
            return await send_email(
                to=user_email,
                subject="Final Notice - Account Will Be Suspended",
                template="final_notice",
                context=context
            )
        except Exception as e:
            logger.error(f"Failed to send final notice to {user_email}: {str(e)}")
            return False
    
    @staticmethod
    async def send_payment_recovery_email(
        user_email: str,
        user_name: str = None
    ) -> bool:
        """Send payment recovery confirmation email"""
        try:
            context = {
                "user_name": user_name or user_email.split("@")[0],
                "support_email": "support@atomiktrading.io",
                "company_name": "Atomik Trading"
            }
            
            return await send_email(
                to=user_email,
                subject="Payment Successful - Service Restored",
                template="payment_recovery",
                context=context
            )
        except Exception as e:
            logger.error(f"Failed to send payment recovery email to {user_email}: {str(e)}")
            return False

# Initialize Jinja2 environment
templates_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
env = Environment(loader=FileSystemLoader(templates_dir))

async def send_email(
    to: str,
    subject: str,
    template: str,
    context: Dict[str, Any]
) -> bool:
    """
    Send an email using a template.
    
    Args:
        to: Recipient email address
        subject: Email subject
        template: Template name without extension
        context: Template context variables
        
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    try:
        # Load the template
        template_path = f"emails/{template}.html"
        template_obj = env.get_template(template_path)
        
        # Render the template
        html_content = template_obj.render(**context)
        
        # Create MIME message
        message = MIMEMultipart()
        message["Subject"] = subject
        message["From"] = settings.SMTP_FROM_EMAIL
        message["To"] = to
        
        # Attach HTML content
        html_part = MIMEText(html_content, "html")
        message.attach(html_part)
        
        # Connect to SMTP server and send email
        with smtplib.SMTP(settings.SMTP_SERVER, settings.SMTP_PORT) as server:
            if settings.SMTP_USE_TLS:
                server.starttls()
            
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                
            server.sendmail(
                settings.SMTP_FROM_EMAIL,
                to,
                message.as_string()
            )
            
        logger.info(f"Email sent successfully to {to}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send email to {to}: {str(e)}")
        return False

async def send_welcome_email(background_tasks: BackgroundTasks, username: str, email: str) -> None:
    """
    Send welcome email to new user asynchronously.
    
    Args:
        background_tasks: FastAPI BackgroundTasks
        username: User's username
        email: User's email address
    """
    context = {
        "username": username
    }
    
    # Add task to background tasks
    background_tasks.add_task(
        send_email,
        to=email,
        subject="Welcome to Atomik Trading!",
        template="welcome_email",
        context=context
    )
    
    logger.info(f"Added welcome email task for user {username} ({email})")

async def send_admin_signup_notification(
    background_tasks: BackgroundTasks, 
    username: str, 
    email: str, 
    tier: str
) -> None:
    """
    Send admin notification about new signup asynchronously.
    
    Args:
        background_tasks: FastAPI BackgroundTasks
        username: User's username
        email: User's email address
        tier: Subscription tier
    """
    # Add timestamp for the admin email
    context = {
        "username": username,
        "email": email,
        "tier": tier,
        "signup_time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    }
    
    # Add task to background tasks - send to admin email
    # Using SMTP_USER email since that's where cruz@atomiktrading.io is configured
    background_tasks.add_task(
        send_email,
        to=settings.SMTP_USER,  # This is cruz@atomiktrading.io
        subject="You got a new Atomik Signup!",
        template="admin_notification",
        context=context
    )
    
    logger.info(f"Added admin notification email task for new signup: {username}")