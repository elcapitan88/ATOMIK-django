from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
import logging
import json
import base64
import uuid
import traceback

from enum import Enum
from pydantic import BaseModel
from datetime import datetime, timedelta

from app.models.order import Order, OrderStatus
from sqlalchemy import or_
from app.models.strategy import ActivatedStrategy
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

class CloseAllPositionsRequest(BaseModel):
    account_ids: List[str]

class AccountUpdateRequest(BaseModel):
    nickname: Optional[str] = None

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
            "nickname": account.nickname,
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

        logger.info(f"Found {len(accounts)} active accounts for user {current_user.id}")
        account_list = []
        
        for account in accounts:
            is_valid = False
            if account.credentials:
                # Log the token state before validation
                logger.info(f"Account {account.account_id} credential check - ID: {account.credentials.id}, expires_at: {account.credentials.expires_at}, is_valid: {account.credentials.is_valid}")
                
                # Only validate token - refresh is now handled by token-refresh-service
                validation_start = datetime.utcnow()
                is_valid = await token_service.validate_token(account.credentials)
                validation_time = (datetime.utcnow() - validation_start).total_seconds() * 1000
                
                logger.info(f"Token validation for account {account.account_id} - Valid: {is_valid}, Took: {validation_time:.2f}ms")
            else:
                logger.warning(f"Account {account.account_id} has no credentials")

            # Build account info with appropriate status
            status = "active"
            if not is_valid:
                status = "token_expired"
                # No need to mark for refresh - token-refresh-service handles this automatically
            elif account.status != "active":
                status = account.status

            account_list.append({
                "account_id": account.account_id,
                "name": account.name,
                "nickname": account.nickname,
                "environment": account.environment,
                "status": status,
                "balance": 0.0,  # This would come from broker API when token is valid
                "active": account.is_active,
                "is_token_expired": not is_valid,
                "last_connected": account.last_connected,
                "token_status": {
                    "valid": is_valid,
                    "expires_at": account.credentials.expires_at.isoformat() if account.credentials and account.credentials.expires_at else None,
                    "message": "Your token will be automatically refreshed by the system." if not is_valid else None
                } if account.credentials else None
            })
            
            # Log the final account state being returned to frontend
            logger.info(f"Returning account state: {account.account_id}, is_token_expired: {not is_valid}")

        return account_list

    except Exception as e:
        logger.error(f"Error fetching accounts: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch accounts: {str(e)}"
        )

@router.post("/accounts/close-all", name="close_all_positions")
async def close_all_positions(
    request: CloseAllPositionsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Close all positions for specified accounts"""
    logger.info(f"Closing positions for accounts: {request.account_ids}")
    
    try:
        # Validate account ownership and get account objects
        accounts = db.query(BrokerAccount).filter(
            BrokerAccount.account_id.in_(request.account_ids),
            BrokerAccount.user_id == current_user.id,
            BrokerAccount.is_active == True
        ).all()

        if not accounts:
            logger.warning(f"No valid accounts found for user {current_user.id}")
            raise HTTPException(
                status_code=404,
                detail="No valid accounts found"
            )

        # Verify account ownership
        found_account_ids = {acc.account_id for acc in accounts}
        missing_accounts = set(request.account_ids) - found_account_ids
        if missing_accounts:
            logger.warning(f"Unauthorized accounts requested: {missing_accounts}")
            raise HTTPException(
                status_code=403,
                detail="Unauthorized access to one or more accounts"
            )

        # Verify all accounts have valid credentials
        invalid_accounts = [acc for acc in accounts if not acc.credentials or not acc.credentials.is_valid]
        if invalid_accounts:
            invalid_ids = [acc.account_id for acc in invalid_accounts]
            raise HTTPException(
                status_code=400,
                detail=f"Invalid credentials for accounts: {invalid_ids}"
            )

        # Get broker instance (assuming all accounts use same broker)
        broker = BaseBroker.get_broker_instance(accounts[0].broker_id, db)
        
        # Execute close all operation
        logger.info(f"Executing close all positions for {len(accounts)} accounts")
        results = await broker.close_all_positions_for_accounts(accounts)

        return {
            "status": "success",
            "results": results,
            "timestamp": datetime.utcnow().isoformat()
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error closing positions: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=str(e)
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
        raise HTTPException(
            status_code=401,
            detail="Account token is expired. The system will automatically refresh it. Please try again in a few minutes."
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
                "nickname": account.nickname,  # Add nickname field
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



    
@router.post("/accounts/{account_id}/discretionary/orders")
async def place_discretionary_order(
    account_id: str,
    order_data: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Place a discretionary trading order"""
    try:
        # Validate account ownership and status
        account = db.query(BrokerAccount).filter(
            BrokerAccount.account_id == account_id,
            BrokerAccount.user_id == current_user.id,
            BrokerAccount.is_active == True
        ).first()

        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        # Validate account is not in use by active strategies
        strategy_check = db.query(ActivatedStrategy).filter(
            or_(
                ActivatedStrategy.account_id == account_id,
                ActivatedStrategy.leader_account_id == account_id
            ),
            ActivatedStrategy.is_active == True
        ).first()

        if strategy_check:
            raise HTTPException(
                status_code=400, 
                detail="Account is currently in use by active strategies"
            )

        # Get broker instance
        broker = BaseBroker.get_broker_instance(account.broker_id, db)

        # Place the order
        order_result = await broker.place_order(account, {
            **order_data,
            'order_type': 'discretionary'  # Mark as discretionary order
        })

        logger.info(f"Tradovate order response: {order_result}")

        # Log the discretionary order
        new_order = Order(
            user_id=current_user.id,
            broker_account_id=account.id,
            broker_order_id=order_result.get('order_id'),
            symbol=order_data['symbol'],
            side=order_data['side'],
            order_type=order_data['type'],
            quantity=order_data['quantity'],
            status=OrderStatus.PENDING,
            submitted_at=datetime.utcnow(),
            broker_response=json.dumps(order_result)
        )
        
        db.add(new_order)
        db.commit()

        return {
            "status": "success",
            "order": order_result,
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"Error placing discretionary order: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to place order: {str(e)}"
        )
    
@router.patch("/accounts/{account_id}")
async def update_account(
    account_id: str,
    update_data: AccountUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update broker account nickname"""
    try:
        # Find the account and verify ownership
        account = db.query(BrokerAccount).filter(
            BrokerAccount.account_id == account_id,
            BrokerAccount.user_id == current_user.id,
            BrokerAccount.is_active == True
        ).first()

        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        # Update the nickname if provided
        if update_data.nickname is not None:
            # Validate nickname length
            if len(update_data.nickname) > 200:
                raise HTTPException(status_code=400, detail="Nickname too long")
            
            # Update the nickname
            account.nickname = update_data.nickname
            account.updated_at = datetime.utcnow()
            
        # Commit the changes
        db.commit()
        
        # Return the updated account
        return {
            "status": "success",
            "message": "Account updated successfully",
            "account": {
                "account_id": account.account_id,
                "name": account.name,
                "nickname": account.nickname,
                "environment": account.environment,
                "updated_at": account.updated_at.isoformat()
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating account nickname: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update account nickname: {str(e)}"
        )
    
