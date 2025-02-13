from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
import logging
import json
import base64
import uuid

from enum import Enum
from pydantic import BaseModel
from datetime import datetime, timedelta


from ....core.security import get_current_user
from ....core.config import settings
from ....db.session import get_db
from ....models.user import User
from ....models.broker import BrokerAccount, BrokerCredentials
from ....core.brokers.base import BaseBroker
from ....core.brokers.config import BrokerEnvironment, BROKER_CONFIGS
from app.services.broker_token_service import BrokerTokenService

router = APIRouter()
logger = logging.getLogger(__name__)

class CredentialType(str, Enum):
    OAUTH = "oauth"
    API_KEY = "api_key"

class BrokerConnectCredentials(BaseModel):
    type: CredentialType
    environment: str

class BrokerConnectRequest(BaseModel):
    environment: str
    credentials: BrokerConnectCredentials


@router.get("/supported")
async def get_supported_brokers():
    """Get list of supported brokers and their features"""
    return {
        "brokers": {
            broker_id: {
                "name": config.name,
                "description": config.description,
                "environments": [env.value for env in config.environments],
                "features": config.features.dict(),
                "connection_method": config.connection_method,
                "supported_assets": config.features.supported_assets
            }
            for broker_id, config in BROKER_CONFIGS.items()
        }
    }

@router.post("/connect")
async def initiate_oauth(
    environment: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Initiate the OAuth flow with Tradovate"""
    try:
        state = base64.urlsafe_b64encode(json.dumps({
            'environment': environment,
            'user_id': current_user.id,
            'timestamp': datetime.utcnow().isoformat(),
            'nonce': str(uuid.uuid4())
        }).encode()).decode()

        # Use the auth URL from settings
        auth_url = settings.TRADOVATE_AUTH_URL

        params = {
            "client_id": settings.TRADOVATE_CLIENT_ID,
            "redirect_uri": settings.TRADOVATE_REDIRECT_URI,
            "response_type": "code",
            "scope": "trading",
            "state": state
        }

        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        full_auth_url = f"{auth_url}?{query_string}"

        return {"auth_url": full_auth_url}

    except Exception as e:
        logger.error(f"OAuth initiation failed: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"OAuth initiation failed: {str(e)}"
        )


@router.get("/accounts")
async def list_broker_accounts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        accounts = db.query(BrokerAccount).filter(
            BrokerAccount.user_id == current_user.id,
            BrokerAccount.is_active == True
        ).all()

        return [account.to_dict() for account in accounts]
    except Exception as e:
        logger.error(f"Error fetching accounts: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

@router.delete("/accounts/{account_id}")
async def disconnect_broker_account(
    account_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        account = db.query(BrokerAccount).filter(
            BrokerAccount.user_id == current_user.id,
            BrokerAccount.account_id == account_id
        ).first()

        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        logger.info(f"Found account: {account.account_id} - {account.name}")
        logger.info(f"Account status before disconnect: active={account.is_active}, status={account.status}")

        # 1. Invalidate any associated tokens
        if account.credentials:
            account.credentials.is_valid = False
            account.credentials.access_token = None
            account.credentials.refresh_token = None

        # 2. Mark account as deleted
        account.is_active = False
        account.status = "disconnected"
        account.deleted_at = datetime.now()
        account.is_deleted = True  # Add this field to your model if not present

        # 3. Commit changes
        db.commit()

        logger.info(f"Successfully disconnected account {account_id}")

        return {
            "status": "success", 
            "message": "Account disconnected and marked for deletion",
            "account_id": account_id
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error during account deletion: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

@router.get("/accounts/{account_id}/status")
async def get_account_status(
    account_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get broker account status and information"""
    account = db.query(BrokerAccount).filter(
        BrokerAccount.account_id == account_id,
        BrokerAccount.user_id == current_user.id,
        BrokerAccount.is_active == True
    ).first()

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    try:
        broker = BaseBroker.get_broker_instance(account.broker_id, db)
        status = await broker.get_account_status(account)

        return {
            "account_id": account.account_id,
            "broker_id": account.broker_id,
            "status": status,
            "last_updated": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"Error getting account status: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get account status: {str(e)}"
        )

@router.get("/accounts/{account_id}/positions")
async def get_positions(
    account_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get current positions for a broker account"""
    account = db.query(BrokerAccount).filter(
        BrokerAccount.account_id == account_id,
        BrokerAccount.user_id == current_user.id,
        BrokerAccount.is_active == True
    ).first()

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    try:
        broker = BaseBroker.get_broker_instance(account.broker_id, db)
        positions = await broker.get_positions(account)

        return {
            "account_id": account.account_id,
            "positions": positions,
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"Error getting positions: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get positions: {str(e)}"
        )

@router.get("/accounts")
async def list_broker_accounts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        token_service = BrokerTokenService(db)
        
        accounts = db.query(BrokerAccount).filter(
            BrokerAccount.user_id == current_user.id,
            BrokerAccount.is_active == True
        ).all()

        account_list = []
        for account in accounts:
            is_valid = False
            if account.credentials:
                # Try to refresh token if needed
                await token_service.refresh_token_if_needed(account.credentials)
                is_valid = await token_service.validate_token(account.credentials)

            account_list.append({
                "account_id": account.account_id,
                "name": account.name,
                "environment": account.environment,
                "status": "active" if is_valid else "token_expired",
                "balance": 0.0,  # This would come from broker API when token is valid
                "active": account.is_active,
                "is_token_expired": not is_valid,
                "last_connected": account.last_connected
            })

        return account_list

    except Exception as e:
        logger.error(f"Error fetching accounts: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch accounts: {str(e)}"
        )
    
async def validate_account_token(account: BrokerAccount, db: Session):
    """Validate account token before trading operations"""
    token_service = BrokerTokenService(db)
    
    if not account.credentials:
        raise HTTPException(
            status_code=401,
            detail="Account has no valid credentials"
        )
        
    is_valid = await token_service.validate_token(account.credentials)
    if not is_valid:
        # Try to refresh
        refreshed = await token_service.refresh_token_if_needed(account.credentials)
        if not refreshed:
            raise HTTPException(
                status_code=401,
                detail="Account token is expired and refresh failed"
            )


@router.post("/accounts/{account_id}/orders")
async def place_order(
    account_id: str,
    order_data: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Place a trading order"""
    account = db.query(BrokerAccount).filter(
        BrokerAccount.account_id == account_id,
        BrokerAccount.user_id == current_user.id,
        BrokerAccount.is_active == True
    ).first()

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    try:
        broker = BaseBroker.get_broker_instance(account.broker_id, db)
        order_result = await broker.place_order(account, order_data)

        return {
            "status": "success",
            "order": order_result,
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"Error placing order: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to place order: {str(e)}"
        )

@router.get("/{broker_id}/accounts")
async def get_broker_accounts(
    broker_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all accounts for a specific broker"""
    try:
        accounts = db.query(BrokerAccount).filter(
            BrokerAccount.user_id == current_user.id,
            BrokerAccount.broker_id == broker_id,
            BrokerAccount.is_active == True
        ).all()

        return [
            {
                "account_id": account.account_id,
                "name": account.name,
                "environment": account.environment,
                "status": account.status,
                "balance": 0.0,  # You'll need to fetch this from broker API
                "active": account.is_active,
                "is_token_expired": not account.credentials.is_valid if account.credentials else True,
                "last_connected": account.last_connected
            }
            for account in accounts
        ]

    except Exception as e:
        logger.error(f"Error fetching {broker_id} accounts: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch accounts: {str(e)}"
        )

@router.delete("/accounts/{account_id}/orders/{order_id}")
async def cancel_order(
    account_id: str,
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Cancel a trading order"""
    account = db.query(BrokerAccount).filter(
        BrokerAccount.account_id == account_id,
        BrokerAccount.user_id == current_user.id,
        BrokerAccount.is_active == True
    ).first()

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    try:
        broker = BaseBroker.get_broker_instance(account.broker_id, db)
        success = await broker.cancel_order(account, order_id)

        if not success:
            raise HTTPException(
                status_code=400,
                detail="Failed to cancel order"
            )

        return {
            "status": "success",
            "message": "Order cancelled successfully"
        }

    except Exception as e:
        logger.error(f"Error cancelling order: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to cancel order: {str(e)}"
        )

@router.get("/accounts/cleanup")
async def cleanup_deleted_accounts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Remove accounts that have been marked as deleted for more than 24 hours"""
    cutoff_time = datetime.utcnow() - timedelta(hours=24)
    deleted_accounts = db.query(BrokerAccount).filter(
        BrokerAccount.deleted_at < cutoff_time,
        BrokerAccount.is_deleted == True
    ).all()
    
    for account in deleted_accounts:
        db.delete(account)
    
    db.commit()
    return {"message": f"Cleaned up {len(deleted_accounts)} accounts"}

@router.get("/{broker_id}/accounts")
async def get_broker_accounts(
    broker_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all accounts for a specific broker"""
    try:
        # Get broker instance
        try:
            broker = BaseBroker.get_broker_instance(broker_id, db)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported broker: {broker_id}"
            )
        except Exception as e:
            logger.error(f"Error creating broker instance: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="Failed to initialize broker service"
            )

        # Fetch accounts using broker implementation
        try:
            accounts = await broker.fetch_accounts(current_user)
            return accounts
        except Exception as e:
            logger.error(f"Error fetching accounts from {broker_id}: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to fetch accounts: {str(e)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_broker_accounts: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred"
        )

