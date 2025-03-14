from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import logging
import json
from sqlalchemy.orm import Session

from ....models.broker import BrokerAccount, BrokerCredentials
from ....models.user import User
from ..base import BaseBroker, AuthenticationError, ConnectionError, OrderError
from ..config import BrokerEnvironment
from ....services.railway_server_manager import railway_server_manager

logger = logging.getLogger(__name__)

class InteractiveBrokersBroker(BaseBroker):
    """
    Implementation of Interactive Brokers broker interface.
    This implementation uses the Railway service manager to provision and
    manage dedicated IBEam servers for each user.
    """

    def __init__(self, broker_id: str, db: Session):
        super().__init__(broker_id, db)
        self.broker_id = broker_id
        self.db = db

    async def authenticate(self, credentials: Dict[str, Any]) -> BrokerCredentials:
        """
        Authenticate with Interactive Brokers.
        For IBEam servers, this is handled during server provisioning.
        """
        # The authentication is handled by the IBEam server
        # This method is just a placeholder to satisfy the interface
        return None

    async def connect_account(
        self,
        user: User,
        account_id: str,
        environment: BrokerEnvironment,
        credentials: Optional[Dict[str, Any]] = None
    ) -> BrokerAccount:
        """
        Connect to an Interactive Brokers trading account.
        This calls the Railway service manager to provision a new IBEam server.
        """
        try:
            # For IB, we need to check if this account already exists
            existing_account = self.db.query(BrokerAccount).filter(
                BrokerAccount.user_id == user.id,
                BrokerAccount.account_id == account_id,
                BrokerAccount.broker_id == self.broker_id,
                BrokerAccount.environment == environment,
                BrokerAccount.is_active == True
            ).first()
            
            if existing_account:
                # If account exists, check if we need to restart the server
                if existing_account.credentials and existing_account.credentials.custom_data:
                    try:
                        service_data = json.loads(existing_account.credentials.custom_data)
                        service_id = service_data.get("railway_service_id")
                        service_status = service_data.get("status")
                        
                        if service_id and service_status in ["stopped", "error"]:
                            # Start the server
                            await railway_server_manager.start_server(service_id)
                            
                            # Update status
                            service_data["status"] = "starting"
                            existing_account.credentials.custom_data = json.dumps(service_data)
                            existing_account.credentials.updated_at = datetime.utcnow()
                            existing_account.status = "connecting"
                            
                            self.db.commit()
                    except Exception as e:
                        logger.error(f"Error restarting IBEam server: {str(e)}")
                
                return existing_account
            
            # IB account needs to be created during the provision_server call
            # which is handled in the API endpoint
            raise ValueError("IB accounts are provisioned through the API endpoint")
            
        except Exception as e:
            logger.error(f"Error connecting to Interactive Brokers account: {str(e)}")
            raise ConnectionError(str(e))

    async def disconnect_account(self, account: BrokerAccount) -> bool:
        """
        Disconnect an Interactive Brokers trading account.
        This stops and cleans up the IBEam server.
        """
        try:
            if not account or account.broker_id != self.broker_id:
                raise ValueError("Invalid account")
            
            # Get Railway service ID if available
            service_id = None
            if account.credentials and account.credentials.custom_data:
                try:
                    service_data = json.loads(account.credentials.custom_data)
                    service_id = service_data.get("railway_service_id")
                except:
                    pass
            
            # Delete Railway service if we have an ID
            if service_id:
                try:
                    await railway_server_manager.delete_server(service_id)
                except Exception as e:
                    logger.error(f"Error deleting Railway service {service_id}: {str(e)}")
            
            # Update account status
            account.is_active = False
            account.is_deleted = True
            account.deleted_at = datetime.utcnow()
            account.status = "deleted"
            
            # Update credentials if they exist
            if account.credentials:
                account.credentials.is_valid = False
                
                if account.credentials.custom_data:
                    try:
                        service_data = json.loads(account.credentials.custom_data)
                        service_data["status"] = "deleted"
                        account.credentials.custom_data = json.dumps(service_data)
                    except:
                        pass
            
            self.db.commit()
            
            return True
            
        except Exception as e:
            logger.error(f"Error disconnecting from Interactive Brokers account: {str(e)}")
            raise ConnectionError(str(e))

    async def fetch_accounts(self, user: User) -> List[Dict[str, Any]]:
        """
        Fetch all Interactive Brokers accounts for a user.
        """
        try:
            accounts = self.db.query(BrokerAccount).filter(
                BrokerAccount.user_id == user.id,
                BrokerAccount.broker_id == self.broker_id,
                BrokerAccount.is_active == True
            ).all()
            
            result = []
            
            for account in accounts:
                account_data = account.to_dict()
                
                # Add Railway status if available
                if account.credentials and account.credentials.custom_data:
                    try:
                        service_data = json.loads(account.credentials.custom_data)
                        account_data["railway_status"] = service_data.get("status", "unknown")
                        
                        # Fetch current Railway status if possible
                        service_id = service_data.get("railway_service_id")
                        if service_id:
                            try:
                                railway_status = await railway_server_manager.get_server_status(service_id)
                                
                                # Update if status has changed
                                if railway_status.get("status") != service_data.get("status"):
                                    service_data["status"] = railway_status.get("status")
                                    account.credentials.custom_data = json.dumps(service_data)
                                    account.credentials.updated_at = datetime.utcnow()
                                    self.db.commit()
                                    
                                account_data["railway_status"] = railway_status.get("status", "unknown")
                            except:
                                # Use existing status if fetch fails
                                pass
                    except:
                        pass
                
                result.append(account_data)
            
            return result
            
        except Exception as e:
            logger.error(f"Error fetching Interactive Brokers accounts: {str(e)}")
            raise ConnectionError(str(e))

    async def get_account_status(self, account: BrokerAccount) -> Dict[str, Any]:
        """
        Get account status and information.
        """
        try:
            if not account or account.broker_id != self.broker_id:
                raise ValueError("Invalid account")
            
            result = {
                "account_id": account.account_id,
                "broker_id": account.broker_id,
                "name": account.name,
                "status": account.status,
                "is_active": account.is_active
            }
            
            # Add Railway status if available
            if account.credentials and account.credentials.custom_data:
                try:
                    service_data = json.loads(account.credentials.custom_data)
                    result["railway_status"] = service_data.get("status", "unknown")
                    
                    # Fetch current Railway status if possible
                    service_id = service_data.get("railway_service_id")
                    if service_id:
                        try:
                            railway_status = await railway_server_manager.get_server_status(service_id)
                            
                            # Update if status has changed
                            if railway_status.get("status") != service_data.get("status"):
                                service_data["status"] = railway_status.get("status")
                                account.credentials.custom_data = json.dumps(service_data)
                                account.credentials.updated_at = datetime.utcnow()
                                self.db.commit()
                                
                            result["railway_status"] = railway_status.get("status", "unknown")
                            result["railway_details"] = railway_status
                        except:
                            # Use existing status if fetch fails
                            pass
                except:
                    pass
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting Interactive Brokers account status: {str(e)}")
            raise ConnectionError(str(e))

    async def get_positions(self, account: BrokerAccount) -> List[Dict[str, Any]]:
        """
        Get current positions for an account.
        This would call the IBEam server API.
        """
        try:
            if not account or account.broker_id != self.broker_id:
                raise ValueError("Invalid account")
            
            # This would call the IBEam server API to get positions
            # For now, return empty list as a placeholder
            return []
            
        except Exception as e:
            logger.error(f"Error getting positions: {str(e)}")
            raise ConnectionError(str(e))

    async def get_orders(self, account: BrokerAccount) -> List[Dict[str, Any]]:
        """
        Get orders for an account.
        This would call the IBEam server API.
        """
        try:
            if not account or account.broker_id != self.broker_id:
                raise ValueError("Invalid account")
            
            # This would call the IBEam server API to get orders
            # For now, return empty list as a placeholder
            return []
            
        except Exception as e:
            logger.error(f"Error getting orders: {str(e)}")
            raise ConnectionError(str(e))

    async def place_order(
        self,
        account: BrokerAccount,
        order_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Place a trading order.
        This would call the IBEam server API.
        """
        try:
            if not account or account.broker_id != self.broker_id:
                raise ValueError("Invalid account")
            
            # This would call the IBEam server API to place an order
            # For now, return empty dict as a placeholder
            return {}
            
        except Exception as e:
            logger.error(f"Error placing order: {str(e)}")
            raise OrderError(str(e))

    async def cancel_order(
        self,
        account: BrokerAccount,
        order_id: str
    ) -> bool:
        """
        Cancel an order.
        This would call the IBEam server API.
        """
        try:
            if not account or account.broker_id != self.broker_id:
                raise ValueError("Invalid account")
            
            # This would call the IBEam server API to cancel an order
            # For now, return True as a placeholder
            return True
            
        except Exception as e:
            logger.error(f"Error canceling order: {str(e)}")
            raise OrderError(str(e))

    async def initialize_oauth(
        self,
        user: User,
        environment: str
    ) -> Dict[str, Any]:
        """
        Initialize OAuth flow.
        For IBEam servers, this is not used as we use direct credentials.
        """
        raise NotImplementedError("Interactive Brokers does not use OAuth")

    async def initialize_api_key(
        self,
        user: User,
        environment: str,
        credentials: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Initialize API key connection.
        For IBEam servers, this is not used as we provision a dedicated server.
        """
        raise NotImplementedError("Interactive Brokers does not use API keys")