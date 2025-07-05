# app/api/v1/endpoints/interactivebrokers.py
from fastapi import APIRouter, Depends, HTTPException, Body, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional
import logging
import json
from datetime import datetime

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.broker import BrokerAccount
from app.core.brokers.base import BaseBroker
from app.services.digital_ocean_server_manager import digital_ocean_server_manager
from app.core.permissions import check_subscription, check_resource_limit

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/connect")
@check_subscription
@check_resource_limit("connected_accounts")
async def connect_ib_account(
    data: Dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None
):
    """
    Connect to Interactive Brokers by provisioning a dedicated IBEam server on Digital Ocean
    """
    try:
        # Extract credentials from request
        credentials = data.get("credentials")
        environment = data.get("environment", "paper")
        
        if not credentials:
            raise HTTPException(status_code=400, detail="Missing credentials")
        
        username = credentials.get("username")
        password = credentials.get("password")
        
        if not username or not password:
            raise HTTPException(status_code=400, detail="Username and password are required")
        
        # Provision IBEam server on Digital Ocean
        result = await digital_ocean_server_manager.provision_server(
            db=db,
            user=current_user,
            ib_username=username,
            ib_password=password,
            environment=environment
        )
        
        # Add background task to check status periodically if needed
        if background_tasks and result.get("service_id"):
            background_tasks.add_task(
                digital_ocean_server_manager.monitor_server_provisioning,
                db_session=db,
                account_id=result.get("account_id"),
                droplet_id=result.get("service_id")
            )
        
        return result
    
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error connecting to IB: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to connect: {str(e)}")

@router.get("/accounts")
@check_subscription
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
@check_subscription
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
            
        # Get droplet_id from credentials
        if not account.credentials or not account.credentials.custom_data:
            raise HTTPException(status_code=400, detail="Account has no associated server")
            
        service_data = json.loads(account.credentials.custom_data)
        droplet_id = service_data.get("droplet_id")
        
        if not droplet_id:
            raise HTTPException(status_code=400, detail="No Digital Ocean droplet ID found")
            
        # Stop the server
        result = await digital_ocean_server_manager.stop_server(droplet_id)
        
        # Update credentials with current status
        if result:
            service_data["status"] = "stopping"
            account.credentials.custom_data = json.dumps(service_data)
            account.credentials.updated_at = datetime.utcnow()
            db.commit()
            
        return {"success": result, "status": "stopping" if result else "error"}
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error stopping IB server: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to stop server: {str(e)}")

@router.post("/accounts/{account_id}/start")
@check_subscription
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
            
        # Get droplet_id from credentials
        if not account.credentials or not account.credentials.custom_data:
            raise HTTPException(status_code=400, detail="Account has no associated server")
            
        service_data = json.loads(account.credentials.custom_data)
        droplet_id = service_data.get("droplet_id")
        
        if not droplet_id:
            raise HTTPException(status_code=400, detail="No Digital Ocean droplet ID found")
            
        # Start the server
        result = await digital_ocean_server_manager.start_server(droplet_id)
        
        # Update credentials with current status
        if result:
            service_data["status"] = "starting"
            account.credentials.custom_data = json.dumps(service_data)
            account.credentials.updated_at = datetime.utcnow()
            db.commit()
            
        return {"success": result, "status": "starting" if result else "error"}
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error starting IB server: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to start server: {str(e)}")

@router.post("/accounts/{account_id}/restart")
@check_subscription
async def restart_ib_server(
    account_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Restart an Interactive Brokers server"""
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
            
        # Get droplet_id from credentials
        if not account.credentials or not account.credentials.custom_data:
            raise HTTPException(status_code=400, detail="Account has no associated server")
            
        service_data = json.loads(account.credentials.custom_data)
        droplet_id = service_data.get("droplet_id")
        
        if not droplet_id:
            raise HTTPException(status_code=400, detail="No Digital Ocean droplet ID found")
            
        # Restart the server
        result = await digital_ocean_server_manager.restart_server(droplet_id)
        
        # Update credentials with current status
        if result:
            service_data["status"] = "restarting"
            account.credentials.custom_data = json.dumps(service_data)
            account.credentials.updated_at = datetime.utcnow()
            db.commit()
            
        return {"success": result, "status": "restarting" if result else "error"}
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error restarting IB server: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to restart server: {str(e)}")

@router.delete("/accounts/{account_id}")
@check_subscription
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
                droplet_id = service_data.get("droplet_id")
                if droplet_id:
                    await digital_ocean_server_manager.delete_server(droplet_id)
            except Exception as e:
                logger.error(f"Error deleting Digital Ocean droplet: {str(e)}")
        
        # Then disconnect the account
        await broker.disconnect_account(account)
        
        return {"status": "success", "message": "Account and server deleted successfully"}
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error deleting IB account: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to delete account: {str(e)}")

@router.get("/accounts/{account_id}/status")
@check_subscription
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
            
        # Get droplet_id from credentials
        if not account.credentials or not account.credentials.custom_data:
            raise HTTPException(status_code=400, detail="Account has no associated server")
            
        service_data = json.loads(account.credentials.custom_data)
        droplet_id = service_data.get("droplet_id")
        
        if not droplet_id:
            raise HTTPException(status_code=400, detail="No Digital Ocean droplet ID found")
            
        # Get server status
        status = await digital_ocean_server_manager.get_server_status(droplet_id)
        
        # Update credentials with current status if changed
        if status and service_data.get("status") != status.get("status"):
            service_data["status"] = status.get("status")
            account.credentials.custom_data = json.dumps(service_data)
            account.credentials.updated_at = datetime.utcnow()
            db.commit()
            
        return status
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error getting server status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get server status: {str(e)}")

@router.get("/accounts/{account_id}/ibeam-health")
@check_subscription
async def check_ibeam_health(
    account_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Check IBeam authentication status for an Interactive Brokers server"""
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
            
        # Get credentials with Digital Ocean info
        if not account.credentials or not account.credentials.do_ip_address:
            return {"authenticated": False, "message": "No server IP address found"}
            
        ip_address = account.credentials.do_ip_address
        
        # Check IBeam health via tickle endpoint
        try:
            import httpx
            async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
                response = await client.get(f"https://{ip_address}:5000/v1/api/tickle")
                
                if response.status_code == 200:
                    data = response.json()
                    authenticated = data.get("iserver", {}).get("authStatus", {}).get("authenticated", False)
                    return {
                        "authenticated": authenticated,
                        "message": "IBeam is running" if authenticated else "IBeam is not authenticated",
                        "raw_response": data
                    }
                else:
                    return {
                        "authenticated": False,
                        "message": f"IBeam returned status code {response.status_code}"
                    }
                    
        except httpx.ConnectError:
            return {
                "authenticated": False,
                "message": "Cannot connect to IBeam service"
            }
        except httpx.TimeoutException:
            return {
                "authenticated": False,
                "message": "IBeam service timeout"
            }
        except Exception as e:
            logger.error(f"IBeam health check error: {str(e)}")
            return {
                "authenticated": False,
                "message": f"IBeam health check failed: {str(e)}"
            }
            
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error checking IBeam health: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to check IBeam health: {str(e)}")