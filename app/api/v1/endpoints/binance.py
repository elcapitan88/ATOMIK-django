from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Dict, List, Any, Optional
import logging
from datetime import datetime

from ....db.session import get_db
from ....core.security import get_current_user
from ....models.user import User
from ....models.broker import BrokerAccount
from ....core.brokers.implementations.binance import create_binance_broker
from ....core.brokers.config import BrokerEnvironment
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


class ApiKeyRequest(BaseModel):
    apiKey: str
    marketType: Optional[str] = "spot"


class TestApiKeyRequest(BaseModel):
    apiKey: str
    marketType: Optional[str] = "spot"


class OrderRequest(BaseModel):
    symbol: str
    side: str  # BUY or SELL
    type: str  # MARKET, LIMIT, etc.
    quantity: float
    price: Optional[float] = None
    timeInForce: Optional[str] = "GTC"
    stopPrice: Optional[float] = None


@router.post("/api-key")
async def save_api_key(
    request: ApiKeyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Save Binance API key for a user"""
    try:
        # Determine broker type (binance or binanceus) from the request or default to binance
        broker_id = 'binance'  # Default to Binance Global
        
        # Create broker instance
        broker = create_binance_broker(broker_id, db)
        
        # Initialize API key connection
        result = await broker.initialize_api_key(
            user=current_user,
            environment='live',
            credentials={'apiKey': request.apiKey}
        )
        
        logger.info(f"Successfully saved API key for user {current_user.id}")
        return {
            "success": True,
            "message": "API key saved successfully",
            "account_id": result.get('account_id')
        }
        
    except ValueError as e:
        logger.warning(f"Invalid API key format from user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error saving API key for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save API key: {str(e)}"
        )


@router.post("/test-api-key")
async def test_api_key(
    request: TestApiKeyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Test Binance API key validity"""
    try:
        # Determine broker type
        broker_id = 'binance'  # Default to Binance Global
        
        # Create broker instance
        broker = create_binance_broker(broker_id, db)
        
        # Parse API key
        if ':' not in request.apiKey:
            raise ValueError("API key must be in format: key:secret")
        
        api_key, secret_key = request.apiKey.split(':', 1)
        
        # Test authentication
        credentials = await broker.authenticate({
            'api_key': api_key,
            'secret_key': secret_key
        })
        
        logger.info(f"Successfully tested API key for user {current_user.id}")
        return {
            "success": True,
            "message": "API key is valid",
            "account_type": credentials.metadata.get('account_type', 'SPOT'),
            "tested_at": datetime.utcnow().isoformat()
        }
        
    except ValueError as e:
        logger.warning(f"Invalid API key format from user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error testing API key for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"API key test failed: {str(e)}"
        )


@router.get("/account/{account_id}/info")
async def get_account_info(
    account_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get Binance account information"""
    try:
        # Get account
        account = db.query(BrokerAccount).filter(
            BrokerAccount.account_id == account_id,
            BrokerAccount.user_id == current_user.id,
            BrokerAccount.broker_id.in_(['binance', 'binanceus'])
        ).first()
        
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found"
            )
        
        # Create broker instance
        broker = create_binance_broker(account.broker_id, db)
        
        # Get account status
        account_status = await broker.get_account_status(account)
        
        return account_status
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting account info for {account_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get account info: {str(e)}"
        )


@router.get("/positions/{account_id}")
async def get_positions(
    account_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get positions for a Binance account"""
    try:
        # Get account
        account = db.query(BrokerAccount).filter(
            BrokerAccount.account_id == account_id,
            BrokerAccount.user_id == current_user.id,
            BrokerAccount.broker_id.in_(['binance', 'binanceus'])
        ).first()
        
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found"
            )
        
        # Create broker instance
        broker = create_binance_broker(account.broker_id, db)
        
        # Get positions
        positions = await broker.get_positions(account)
        
        return {
            "account_id": account_id,
            "positions": positions,
            "count": len(positions)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting positions for {account_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get positions: {str(e)}"
        )


@router.get("/orders/{account_id}")
async def get_orders(
    account_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get orders for a Binance account"""
    try:
        # Get account
        account = db.query(BrokerAccount).filter(
            BrokerAccount.account_id == account_id,
            BrokerAccount.user_id == current_user.id,
            BrokerAccount.broker_id.in_(['binance', 'binanceus'])
        ).first()
        
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found"
            )
        
        # Create broker instance
        broker = create_binance_broker(account.broker_id, db)
        
        # Get orders
        orders = await broker.get_orders(account)
        
        return {
            "account_id": account_id,
            "orders": orders,
            "count": len(orders)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting orders for {account_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get orders: {str(e)}"
        )


@router.post("/order/{account_id}")
async def place_order(
    account_id: str,
    order_request: OrderRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Place an order on Binance"""
    try:
        # Get account
        account = db.query(BrokerAccount).filter(
            BrokerAccount.account_id == account_id,
            BrokerAccount.user_id == current_user.id,
            BrokerAccount.broker_id.in_(['binance', 'binanceus'])
        ).first()
        
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found"
            )
        
        # Create broker instance
        broker = create_binance_broker(account.broker_id, db)
        
        # Prepare order data
        order_data = {
            'symbol': order_request.symbol,
            'side': order_request.side,
            'type': order_request.type,
            'quantity': order_request.quantity,
            'timeInForce': order_request.timeInForce
        }
        
        if order_request.price:
            order_data['price'] = order_request.price
        if order_request.stopPrice:
            order_data['stopPrice'] = order_request.stopPrice
        
        # Place order
        result = await broker.place_order(account, order_data)
        
        logger.info(f"Order placed successfully for account {account_id}")
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error placing order for {account_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to place order: {str(e)}"
        )


@router.delete("/order/{account_id}")
async def cancel_order(
    account_id: str,
    symbol: str,
    orderId: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Cancel an order on Binance"""
    try:
        # Get account
        account = db.query(BrokerAccount).filter(
            BrokerAccount.account_id == account_id,
            BrokerAccount.user_id == current_user.id,
            BrokerAccount.broker_id.in_(['binance', 'binanceus'])
        ).first()
        
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found"
            )
        
        # Create broker instance
        broker = create_binance_broker(account.broker_id, db)
        
        # Cancel order
        success = await broker.cancel_order(account, f"{symbol}_{orderId}")
        
        if success:
            logger.info(f"Order {orderId} cancelled successfully for account {account_id}")
            return {"success": True, "message": "Order cancelled successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to cancel order"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling order {orderId} for {account_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cancel order: {str(e)}"
        )


@router.get("/balance/{account_id}")
async def get_balance(
    account_id: str,
    asset: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get balance for a Binance account"""
    try:
        # Get account
        account = db.query(BrokerAccount).filter(
            BrokerAccount.account_id == account_id,
            BrokerAccount.user_id == current_user.id,
            BrokerAccount.broker_id.in_(['binance', 'binanceus'])
        ).first()
        
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found"
            )
        
        # Create broker instance
        broker = create_binance_broker(account.broker_id, db)
        
        # Get positions (which include balances for spot accounts)
        positions = await broker.get_positions(account)
        
        # Filter by asset if specified
        if asset:
            positions = [p for p in positions if p['symbol'] == asset]
        
        return {
            "account_id": account_id,
            "balances": positions
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting balance for {account_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get balance: {str(e)}"
        )


@router.get("/exchange-info/{account_id}")
async def get_exchange_info(
    account_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get exchange information for Binance"""
    try:
        # Get account
        account = db.query(BrokerAccount).filter(
            BrokerAccount.account_id == account_id,
            BrokerAccount.user_id == current_user.id,
            BrokerAccount.broker_id.in_(['binance', 'binanceus'])
        ).first()
        
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found"
            )
        
        # For now, return basic exchange info
        # This could be expanded to fetch real exchange info from Binance API
        return {
            "exchange": "Binance" if account.broker_id == 'binance' else "Binance.US",
            "account_type": account.metadata.get('account_type', 'SPOT'),
            "permissions": account.metadata.get('permissions', []),
            "rate_limits": {
                "requests_per_second": 10,
                "requests_per_minute": 1200,
                "weight_per_minute": 6000
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting exchange info for {account_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get exchange info: {str(e)}"
        )


@router.get("/health")
async def health_check():
    """Health check endpoint for Binance integration"""
    return {
        "status": "healthy",
        "service": "binance-broker",
        "timestamp": datetime.utcnow().isoformat(),
        "supported_exchanges": ["binance", "binanceus"],
        "supported_markets": ["spot", "futures"]
    }