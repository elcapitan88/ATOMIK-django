from fastapi import APIRouter, Depends, HTTPException, Body, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional
import logging
import json

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.broker import BrokerAccount
from app.core.brokers.base import BaseBroker
from app.services.railway_server_manager import railway_server_manager

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/connect")
async def connect_ib_account(
    data: Dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None
):
    """
    Connect to Interactive Brokers by provisioning a dedicated IBEam server
    """
    try:
        # Extract credentials from request
        credentials = data.get("credentials")
        environment = data.get("environment", "demo")
        
        if not credentials:
            raise HTTPException(status_code=400, detail="Missing credentials")
        
        username = credentials.get("username")
        password = credentials.get("password")
        
        if not username or not password:
            raise HTTPException(status_code=400, detail="Username and password are required")
        
        # Provision IBEam server on Railway
        result = await railway_server_manager.provision_server(
            db=db,
            user=current_user,
            ib_username=username,
            ib_password=password
        )
        
        # Add background task to check status periodically if needed
        if background_tasks and result.get("service_id"):
            background_tasks.add_task(
                railway_server_manager.monitor_server_provisioning,
                db_session=db,
                account_id=result.get("account_id"),
                service_id=result.get("service_id")
            )
        
        return result
    
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error connecting to IB: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to connect: {str(e)}")

@router.get("/accounts")
async def get_ib_accounts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all Interactive Brokers accounts for the current user"""
    try:
        # Get broker implementation
        broker = BaseBroker.get_broker_instance("interactivebrokers", db)
        
        # Use the broker to fetch accounts
        accounts = await broker.fetch_accounts(current_user)
        return accounts
        
    except Exception as e:
        logger.error(f"Error getting IB accounts: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get accounts: {str(e)}")

@router.post("/accounts/{account_id}/stop")
async def stop_ib_server(
    account_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Stop an Interactive Brokers server"""
    try:
        # Get the account
        account = db.query(BrokerAccount).filter(
            BrokerAccount.user_id == current_user.id,
            BrokerAccount.account_id == account_id,
            BrokerAccount.broker_id == "interactivebrokers",
            BrokerAccount.is_active == True
        ).first()
        
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
            
        # Get service_id from credentials
        if not account.credentials or not account.credentials.custom_data:
            raise HTTPException(status_code=400, detail="Account has no associated server")
            
        service_data = json.loads(account.credentials.custom_data)
        service_id = service_data.get("railway_service_id")
        
        if not service_id:
            raise HTTPException(status_code=400, detail="No Railway service ID found")
            
        # Stop the server
        result = await railway_server_manager.stop_server(service_id)
        return result
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error stopping IB server: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to stop server: {str(e)}")

@router.post("/accounts/{account_id}/start")
async def start_ib_server(
    account_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Start an Interactive Brokers server"""
    try:
        # Get the account
        account = db.query(BrokerAccount).filter(
            BrokerAccount.user_id == current_user.id,
            BrokerAccount.account_id == account_id,
            BrokerAccount.broker_id == "interactivebrokers",
            BrokerAccount.is_active == True
        ).first()
        
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
            
        # Get service_id from credentials
        if not account.credentials or not account.credentials.custom_data:
            raise HTTPException(status_code=400, detail="Account has no associated server")
            
        service_data = json.loads(account.credentials.custom_data)
        service_id = service_data.get("railway_service_id")
        
        if not service_id:
            raise HTTPException(status_code=400, detail="No Railway service ID found")
            
        # Start the server
        result = await railway_server_manager.start_server(service_id)
        return result
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error starting IB server: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to start server: {str(e)}")

@router.delete("/accounts/{account_id}")
async def delete_ib_account(
    account_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete an Interactive Brokers account and its server"""
    try:
        # Get broker implementation
        broker = BaseBroker.get_broker_instance("interactivebrokers", db)
        
        # Get the account
        account = db.query(BrokerAccount).filter(
            BrokerAccount.user_id == current_user.id,
            BrokerAccount.account_id == account_id,
            BrokerAccount.broker_id == "interactivebrokers",
            BrokerAccount.is_active == True
        ).first()
        
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
            
        # Delete the server first if applicable
        if account.credentials and account.credentials.custom_data:
            try:
                service_data = json.loads(account.credentials.custom_data)
                service_id = service_data.get("railway_service_id")
                if service_id:
                    await railway_server_manager.delete_server(service_id)
            except Exception as e:
                logger.error(f"Error deleting Railway server: {str(e)}")
        
        # Then disconnect the account
        await broker.disconnect_account(account)
        
        return {"status": "success", "message": "Account and server deleted successfully"}
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error deleting IB account: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to delete account: {str(e)}")

@router.get("/accounts/{account_id}/status")
async def get_server_status(
    account_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get status of an Interactive Brokers server"""
    try:
        # Get the account
        account = db.query(BrokerAccount).filter(
            BrokerAccount.user_id == current_user.id,
            BrokerAccount.account_id == account_id,
            BrokerAccount.broker_id == "interactivebrokers",
            BrokerAccount.is_active == True
        ).first()
        
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
            
        # Get service_id from credentials
        if not account.credentials or not account.credentials.custom_data:
            raise HTTPException(status_code=400, detail="Account has no associated server")
            
        service_data = json.loads(account.credentials.custom_data)
        service_id = service_data.get("railway_service_id")
        
        if not service_id:
            raise HTTPException(status_code=400, detail="No Railway service ID found")
            
        # Get server status
        status = await railway_server_manager.get_server_status(service_id)
        return status
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error getting server status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get server status: {str(e)}")