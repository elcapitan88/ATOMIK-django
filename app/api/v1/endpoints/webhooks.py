from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
import hmac
import hashlib
import secrets
from datetime import datetime
import logging

from ....core.security import get_current_user
from ....core.permissions import check_subscription_feature
from ....db.session import get_db
from ....models.user import User
from ....models.webhook import Webhook, WebhookLog
from ....models.subscription import SubscriptionTier
from ....schemas.webhook import (
    WebhookCreate,
    WebhookUpdate,
    WebhookOut,
    WebhookLogOut,
    WebhookPayload
)
from ....services.webhook_service import WebhookProcessor
from ....core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

def get_client_ip(request: Request) -> str:
    """Get client IP address from request"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host

def generate_webhook_url(webhook: Webhook) -> str:
    """Generate complete webhook URL"""
    base_url = settings.SERVER_HOST.rstrip('/')
    return f"{base_url}/api/v1/webhooks/{webhook.token}"

@router.post("/generate", response_model=WebhookOut)
#@check_subscription_feature(SubscriptionTier.STARTED)
async def generate_webhook(
    webhook_in: WebhookCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        logger.info(f"Received webhook creation request")
        logger.info(f"Webhook data: {webhook_in.dict()}")
        logger.info(f"Current user: {current_user.id}")

        # Create webhook
        webhook = Webhook(
            user_id=current_user.id,
            token=secrets.token_urlsafe(32),
            secret_key=secrets.token_hex(32),
            name=webhook_in.name if webhook_in.name else "New Webhook",
            source_type=webhook_in.source_type,
            details=webhook_in.details,
            allowed_ips=webhook_in.allowed_ips,
            max_triggers_per_minute=webhook_in.max_triggers_per_minute or 60,
            require_signature=webhook_in.require_signature if webhook_in.require_signature is not None else True,
            max_retries=webhook_in.max_retries or 3,
            is_active=True,
            created_at=datetime.utcnow()
        )

        db.add(webhook)
        db.commit()
        db.refresh(webhook)

        # Create the webhook URL
        webhook_url = generate_webhook_url(webhook)

        # Return response
        return WebhookOut(
            id=webhook.id,
            token=webhook.token,
            user_id=webhook.user_id,
            name=webhook.name,
            source_type=webhook.source_type,
            details=webhook.details,
            secret_key=webhook.secret_key,
            allowed_ips=webhook.allowed_ips,
            max_triggers_per_minute=webhook.max_triggers_per_minute,
            require_signature=webhook.require_signature,
            max_retries=webhook.max_retries,
            is_active=webhook.is_active,
            created_at=webhook.created_at,
            last_triggered=webhook.last_triggered,
            webhook_url=webhook_url
        )

    except Exception as e:
        logger.error(f"Error generating webhook: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

@router.post("/{token}")
async def webhook_endpoint(
    token: str,
    request: Request,
    payload: WebhookPayload,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    secret: Optional[str] = None  # Add this to get the secret from query params
):
    """Handle incoming webhook requests"""
    try:
        # Get webhook
        webhook = db.query(Webhook).filter(
            Webhook.token == token,
            Webhook.is_active == True
        ).first()
        
        if not webhook:
            raise HTTPException(status_code=404, detail="Webhook not found")

        # Verify secret if required
        if webhook.require_signature:
            if not secret:
                raise HTTPException(
                    status_code=401,
                    detail="Secret parameter required"
                )
            
            if secret != webhook.secret_key:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid secret"
                )

        # Check IP allowlist if configured
        client_ip = get_client_ip(request)
        if webhook.allowed_ips:
            allowed_ips = [ip.strip() for ip in webhook.allowed_ips.split(',')]
            if client_ip not in allowed_ips:
                raise HTTPException(
                    status_code=403,
                    detail="IP not allowed"
                )

        # Process webhook in background
        webhook_processor = WebhookProcessor(db)
        background_tasks.add_task(
            webhook_processor.process_webhook,
            webhook=webhook,
            payload=payload.dict(),
            client_ip=client_ip
        )

        return {
            "status": "accepted",
            "message": "Webhook received and being processed",
            "webhook_id": webhook.id,
            "timestamp": datetime.utcnow().isoformat()
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Webhook processing failed: {str(e)}"
        )

@router.get("/list", response_model=List[WebhookOut])
#@check_subscription_feature(SubscriptionTier.STARTED)
async def list_webhooks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all webhooks for the current user"""
    webhooks = db.query(Webhook).filter(
        Webhook.user_id == current_user.id
    ).all()

    return [
        WebhookOut(
            id=webhook.id,
            token=webhook.token,
            user_id=webhook.user_id,
            name=webhook.name,
            source_type=webhook.source_type,
            details=webhook.details,
            allowed_ips=webhook.allowed_ips,
            max_triggers_per_minute=webhook.max_triggers_per_minute,
            require_signature=webhook.require_signature,
            max_retries=webhook.max_retries,
            is_active=webhook.is_active,
            created_at=webhook.created_at,
            last_triggered=webhook.last_triggered,
            secret_key=webhook.secret_key,  # Include the secret key
            webhook_url=generate_webhook_url(webhook)
        ) for webhook in webhooks
    ]

@router.post("/generate", response_model=WebhookOut)
async def generate_webhook(
    webhook_in: WebhookCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        logger.info(f"Received webhook creation request")
        logger.info(f"Webhook data: {webhook_in.dict()}")
        logger.info(f"Current user: {current_user.id}")

        # Generate webhook
        webhook = Webhook(
            user_id=current_user.id,
            token=secrets.token_urlsafe(32),
            secret_key=secrets.token_hex(32),  # Make sure this is generated
            name=webhook_in.name if webhook_in.name else "New Webhook",
            source_type=webhook_in.source_type,
            details=webhook_in.details,
            allowed_ips=webhook_in.allowed_ips,
            max_triggers_per_minute=webhook_in.max_triggers_per_minute or 60,
            require_signature=webhook_in.require_signature if webhook_in.require_signature is not None else True,
            max_retries=webhook_in.max_retries or 3,
            is_active=True,
            created_at=datetime.utcnow()
        )

        db.add(webhook)
        db.commit()
        db.refresh(webhook)

        # Return response with all required fields
        return WebhookOut(
            id=webhook.id,
            token=webhook.token,
            user_id=webhook.user_id,
            secret_key=webhook.secret_key,  # Include the secret_key
            name=webhook.name,
            source_type=webhook.source_type,
            details=webhook.details,
            allowed_ips=webhook.allowed_ips,
            max_triggers_per_minute=webhook.max_triggers_per_minute,
            require_signature=webhook.require_signature,
            max_retries=webhook.max_retries,
            is_active=webhook.is_active,
            created_at=webhook.created_at,
            last_triggered=webhook.last_triggered,
            webhook_url=generate_webhook_url(webhook)
        )

    except Exception as e:
        logger.error(f"Error generating webhook: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        db.rollback()  # Roll back on error
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

@router.patch("/{token}", response_model=WebhookOut)
#@check_subscription_feature(SubscriptionTier.STARTED)
async def update_webhook(
    token: str,
    webhook_update: WebhookUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update webhook settings"""
    webhook = db.query(Webhook).filter(
        Webhook.token == token,
        Webhook.user_id == current_user.id
    ).first()

    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    # Update fields
    for key, value in webhook_update.dict(exclude_unset=True).items():
        setattr(webhook, key, value)

    db.commit()
    db.refresh(webhook)

    return WebhookOut(
        **webhook.__dict__,
        webhook_url=generate_webhook_url(webhook)
    )

@router.delete("/{token}")
#@check_subscription_feature(SubscriptionTier.STARTED)
async def delete_webhook(
    token: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a webhook"""
    webhook = db.query(Webhook).filter(
        Webhook.token == token,
        Webhook.user_id == current_user.id
    ).first()

    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    db.delete(webhook)
    db.commit()

    return {
        "status": "success",
        "message": "Webhook deleted successfully"
    }

@router.get("/{token}/logs", response_model=List[WebhookLogOut])
#@check_subscription_feature(SubscriptionTier.STARTED)
async def get_webhook_logs(
    token: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = 50,
    skip: int = 0
):
    """Get logs for a specific webhook"""
    webhook = db.query(Webhook).filter(
        Webhook.token == token,
        Webhook.user_id == current_user.id
    ).first()

    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    logs = db.query(WebhookLog).filter(
        WebhookLog.webhook_id == webhook.id
    ).order_by(
        WebhookLog.triggered_at.desc()
    ).offset(skip).limit(limit).all()

    return logs

@router.post("/{token}/test")
#@check_subscription_feature(SubscriptionTier.STARTED)
async def test_webhook(
    token: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Test a webhook with sample data"""
    webhook = db.query(Webhook).filter(
        Webhook.token == token,
        Webhook.user_id == current_user.id
    ).first()

    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    # Create test payload
    test_payload = {
        "action": "BUY",
        "symbol": "ES",
        "quantity": 1,
        "order_type": "MARKET",
        "test": True,
        "timestamp": datetime.utcnow().isoformat()
    }

    try:
        webhook_processor = WebhookProcessor(db)
        result = await webhook_processor.process_webhook(
            webhook=webhook,
            payload=test_payload,
            client_ip="127.0.0.1"
        )

        return {
            "status": "success",
            "message": "Test webhook triggered successfully",
            "webhook_url": generate_webhook_url(webhook),
            "test_payload": test_payload,
            "result": result
        }

    except Exception as e:
        logger.error(f"Error testing webhook: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Webhook test failed: {str(e)}"
        )