# app/core/brokers/implementations/interactivebrokers.py
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import logging
import json
import httpx
from sqlalchemy.orm import Session

from ....models.broker import BrokerAccount, BrokerCredentials
from ....models.user import User
from ..base import BaseBroker, AuthenticationError, ConnectionError, OrderError
from ..config import BrokerEnvironment
from ....services.digital_ocean_server_manager import digital_ocean_server_manager  # Updated import

logger = logging.getLogger(__name__)

class InteractiveBrokersBroker(BaseBroker):
    """
    Implementation of Interactive Brokers broker interface.
    This implementation uses the Digital Ocean service manager to provision and
    manage dedicated IBEam servers for each user.
    """

    def __init__(self, broker_id: str, db: Session):
        super().__init__(broker_id, db)
        self.broker_id = broker_id
        self.db = db
        # HTTP client for direct IBEam communication
        self.http_client = httpx.AsyncClient(verify=False, timeout=30.0)

    async def _get_ibeam_ip(self, account: BrokerAccount) -> Optional[str]:
        """Get the IBEam server IP address from account credentials"""
        if not account.credentials or not account.credentials.custom_data:
            return None
            
        try:
            service_data = json.loads(account.credentials.custom_data)
            ip_address = service_data.get("ip_address")
            
            # If no IP address, try to get it from Digital Ocean
            if not ip_address:
                droplet_id = service_data.get("droplet_id")
                if droplet_id:
                    status = await digital_ocean_server_manager.get_server_status(droplet_id)
                    ip_address = status.get("ip_address")
                    
                    # Update the stored IP address
                    if ip_address:
                        service_data["ip_address"] = ip_address
                        account.credentials.custom_data = json.dumps(service_data)
                        self.db.commit()
            
            return ip_address
                
        except Exception as e:
            logger.error(f"Error getting IBEam IP: {str(e)}")
            
        return None

    async def _check_ibeam_auth(self, ip_address: str) -> bool:
        """Check if IBEam server is authenticated"""
        try:
            async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
                response = await client.get(f"https://{ip_address}:5000/v1/api/tickle")
                data = response.json()
                return data.get("iserver", {}).get("authStatus", {}).get("authenticated", False)
        except Exception as e:
            logger.error(f"Error checking IBEam auth: {str(e)}")
            return False

    async def _search_contract(self, ip_address: str, symbol: str) -> Optional[int]:
        """Search for contract ID by symbol"""
        try:
            # For futures, we need to parse the symbol
            # Examples: 
            # ESZ24 -> ES (2 chars) + Z24 (month/year)
            # MESU5 -> MES (3 chars) + U5 (month/year)
            if len(symbol) >= 4:
                # Handle 3-character roots (MES, NKD, etc.)
                if symbol.startswith(('MES', 'NKD', 'RTY', 'YMM')):
                    root = symbol[:3]
                else:
                    # Handle 2-character roots (ES, NQ, CL, etc.)
                    root = symbol[:2]
                
                logger.info(f"Searching for futures contract: symbol={symbol}, root={root}")
                
                # Search for the contract directly
                async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
                    response = await client.get(f"https://{ip_address}:5000/v1/api/iserver/secdef/search?symbol={root}&secType=FUT")
                    result = response.json()
                
                logger.info(f"Contract search result for {root}: {len(result) if result else 0} contracts found")
                
                if result and len(result) > 0:
                    # Find the specific contract by matching the full symbol
                    for contract in result:
                        if contract.get("symbol") == symbol:
                            logger.info(f"Found exact match: {symbol} -> conid {contract.get('conid')}")
                            return contract.get("conid")
                    
                    # If exact match not found, return first contract
                    first_conid = result[0].get("conid")
                    logger.warning(f"No exact match for {symbol}, using first contract: conid {first_conid}")
                    return first_conid
                    
        except Exception as e:
            logger.error(f"Error searching contract: {str(e)}")
            
        return None

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
        This calls the Digital Ocean service manager to provision a new IBEam server.
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
                        droplet_id = service_data.get("droplet_id")
                        service_status = service_data.get("status")
                        
                        if droplet_id and service_status in ["stopped", "off", "error"]:
                            # Start the server
                            await digital_ocean_server_manager.start_server(droplet_id)
                            
                            # Update status
                            service_data["status"] = "starting"
                            existing_account.credentials.custom_data = json.dumps(service_data)
                            existing_account.credentials.updated_at = datetime.utcnow()
                            existing_account.status = "connecting"
                            
                            self.db.commit()
                    except Exception as e:
                        logger.error(f"Error restarting IBEam server on Digital Ocean: {str(e)}")
                
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
            
            # Get Digital Ocean droplet ID if available
            droplet_id = None
            if account.credentials and account.credentials.custom_data:
                try:
                    service_data = json.loads(account.credentials.custom_data)
                    droplet_id = service_data.get("droplet_id")
                except:
                    pass
            
            # Delete Digital Ocean droplet if we have an ID
            if droplet_id:
                try:
                    await digital_ocean_server_manager.delete_server(droplet_id)
                except Exception as e:
                    logger.error(f"Error deleting Digital Ocean droplet {droplet_id}: {str(e)}")
            
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
                
                # Add Digital Ocean status if available
                if account.credentials and account.credentials.custom_data:
                    try:
                        service_data = json.loads(account.credentials.custom_data)
                        account_data["digital_ocean_status"] = service_data.get("status", "unknown")
                        
                        # Fetch current Digital Ocean status if possible
                        droplet_id = service_data.get("droplet_id")
                        if droplet_id:
                            try:
                                do_status = await digital_ocean_server_manager.get_server_status(droplet_id)
                                
                                # Update if status has changed
                                if do_status.get("status") != service_data.get("status"):
                                    service_data["status"] = do_status.get("status")
                                    account.credentials.custom_data = json.dumps(service_data)
                                    account.credentials.updated_at = datetime.utcnow()
                                    self.db.commit()
                                    
                                account_data["digital_ocean_status"] = do_status.get("status", "unknown")
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
            
            # Add Digital Ocean status if available
            if account.credentials and account.credentials.custom_data:
                try:
                    service_data = json.loads(account.credentials.custom_data)
                    result["digital_ocean_status"] = service_data.get("status", "unknown")
                    
                    # Fetch current Digital Ocean status if possible
                    droplet_id = service_data.get("droplet_id")
                    if droplet_id:
                        try:
                            do_status = await digital_ocean_server_manager.get_server_status(droplet_id)
                            
                            # Update if status has changed
                            if do_status.get("status") != service_data.get("status"):
                                service_data["status"] = do_status.get("status")
                                account.credentials.custom_data = json.dumps(service_data)
                                account.credentials.updated_at = datetime.utcnow()
                                self.db.commit()
                                
                            result["digital_ocean_status"] = do_status.get("status", "unknown")
                            result["digital_ocean_details"] = do_status
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
        """Get current positions from IBEam server"""
        try:
            if not account or account.broker_id != self.broker_id:
                raise ValueError("Invalid account")
            
            ip_address = await self._get_ibeam_ip(account)
            if not ip_address:
                return []
            
            # Get positions from IBEam directly
            async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
                response = await client.get(f"https://{ip_address}:5000/v1/api/portfolio/{account.account_id}/positions/0")
                result = response.json()
            
            if result:
                # Normalize positions
                normalized = []
                for pos in result:
                    normalized.append({
                        "symbol": pos.get("contractDesc", ""),
                        "quantity": pos.get("position", 0),
                        "side": "long" if pos.get("position", 0) > 0 else "short",
                        "entry_price": pos.get("avgCost", 0),
                        "current_price": pos.get("mktPrice", 0),
                        "unrealized_pnl": pos.get("unrealizedPnl", 0),
                        "realized_pnl": pos.get("realizedPnl", 0)
                    })
                
                return normalized
                
            return []
            
        except Exception as e:
            logger.error(f"Error getting positions: {str(e)}")
            return []

    async def get_orders(self, account: BrokerAccount) -> List[Dict[str, Any]]:
        """Get orders from IBEam server"""
        try:
            if not account or account.broker_id != self.broker_id:
                raise ValueError("Invalid account")
            
            ip_address = await self._get_ibeam_ip(account)
            if not ip_address:
                return []
            
            # Get live orders
            response = await self.http_client.get(
                f"https://{ip_address}:5000/v1/api/iserver/account/orders"
            )
            
            if response.status_code == 200:
                orders = response.json()
                
                # Normalize orders
                normalized = []
                for order in orders.get("orders", []):
                    normalized.append({
                        "order_id": order.get("orderId"),
                        "status": order.get("status", "").lower(),
                        "symbol": order.get("ticker", ""),
                        "side": order.get("side", "").lower(),
                        "quantity": order.get("totalSize", 0),
                        "filled_quantity": order.get("filledQuantity", 0),
                        "order_type": order.get("orderType", ""),
                        "price": order.get("price", 0)
                    })
                
                return normalized
                
            return []
            
        except Exception as e:
            logger.error(f"Error getting orders: {str(e)}")
            return []

    async def place_order(
        self,
        account: BrokerAccount,
        order_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Place a trading order through IBEam server"""
        try:
            if not account or account.broker_id != self.broker_id:
                raise ValueError("Invalid account")
            
            # Get IBEam server IP
            ip_address = await self._get_ibeam_ip(account)
            if not ip_address:
                raise OrderError("IBEam server not configured or not ready")
            
            # Check if authenticated
            if not await self._check_ibeam_auth(ip_address):
                raise OrderError("IBEam server not authenticated")
            
            # Get contract ID for the symbol
            contract_id = await self._search_contract(ip_address, order_data["symbol"])
            if not contract_id:
                raise OrderError(f"Could not find contract for symbol: {order_data['symbol']}")
            
            # Get real IB account ID from custom_data
            real_ib_account_id = self._get_real_ib_account_id(account)
            if not real_ib_account_id:
                raise OrderError("Real IB account ID not found. Please ensure account is properly authenticated.")
            
            # Map order types to IB format
            order_type_map = {
                "MARKET": "MKT",
                "MKT": "MKT", 
                "LIMIT": "LMT",
                "LMT": "LMT",
                "STOP": "STP",
                "STP": "STP"
            }
            
            order_type = order_data.get("type", "MARKET").upper()
            ib_order_type = order_type_map.get(order_type, "MKT")
            
            # Prepare IB order format with correct data types
            ib_order = {
                "acctId": real_ib_account_id,  # String
                "conid": int(contract_id),     # Integer (required by IB)
                "orderType": ib_order_type,   # String - use IB format
                "side": order_data["side"].upper(),  # String: BUY or SELL
                "quantity": int(order_data["quantity"]),  # Integer (required by IB)
                "tif": order_data.get("time_in_force", "GTC").upper()  # String
            }
            
            logger.info(f"Placing IB order: {ib_order}")
            
            # Add price for limit orders
            if order_data.get("type") == "LIMIT" and order_data.get("price"):
                ib_order["price"] = order_data["price"]
            
            # Place the order
            response = await self.http_client.post(
                f"https://{ip_address}:5000/v1/api/iserver/account/{real_ib_account_id}/orders",
                json={"orders": [ib_order]}
            )
            
            if response.status_code != 200:
                error_data = response.json()
                raise OrderError(f"Order failed: {error_data}")
            
            result = response.json()
            logger.info(f"IB order response: {result}")
            
            # Handle IB's reply confirmation if needed
            if result and isinstance(result, list) and result[0].get("id"):
                # Confirm the order
                reply_id = result[0]["id"]
                confirm_response = await self.http_client.post(
                    f"https://{ip_address}:5000/v1/api/iserver/reply/{reply_id}",
                    json={"confirmed": True}
                )
                
                if confirm_response.status_code == 200:
                    final_result = confirm_response.json()
                    
                    # Return normalized response
                    return {
                        "order_id": final_result[0].get("order_id", "") if final_result else "",
                        "status": "submitted",
                        "symbol": order_data["symbol"],
                        "side": order_data["side"],
                        "quantity": order_data["quantity"],
                        "order_type": order_data.get("type", "MARKET"),
                        "created_at": datetime.utcnow().isoformat()
                    }
            
            # Return the result
            if result and isinstance(result, list) and len(result) > 0:
                return self.normalize_order_response(result[0])
            else:
                # If no standard response, create a basic success response
                return {
                    "order_id": "unknown",
                    "status": "submitted",
                    "symbol": order_data["symbol"],
                    "side": order_data["side"],
                    "quantity": order_data["quantity"],
                    "order_type": order_data.get("type", "MARKET"),
                    "created_at": datetime.utcnow().isoformat(),
                    "message": "Order submitted to IB successfully"
                }
            
        except Exception as e:
            logger.error(f"Error placing IB order: {str(e)}")
            raise OrderError(str(e))

    async def cancel_order(
        self,
        account: BrokerAccount,
        order_id: str
    ) -> bool:
        """Cancel an order through IBEam server"""
        try:
            if not account or account.broker_id != self.broker_id:
                raise ValueError("Invalid account")
            
            ip_address = await self._get_ibeam_ip(account)
            if not ip_address:
                raise OrderError("IBEam server not configured or not ready")
            
            # Cancel the order
            response = await self.http_client.delete(
                f"https://{ip_address}:5000/v1/api/iserver/account/{account.account_id}/order/{order_id}"
            )
            
            if response.status_code == 200:
                result = response.json()
                # IB may require confirmation for cancel
                if result and isinstance(result, dict) and result.get("id"):
                    # Confirm the cancellation
                    reply_id = result["id"]
                    confirm_response = await self.http_client.post(
                        f"https://{ip_address}:5000/v1/api/iserver/reply/{reply_id}",
                        json={"confirmed": True}
                    )
                    return confirm_response.status_code == 200
                
                return True
            
            return False
            
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

    def _get_real_ib_account_id(self, account: BrokerAccount) -> str:
        """Extract the real IB account ID from custom_data"""
        try:
            if account.credentials and account.credentials.custom_data:
                import json
                service_data = json.loads(account.credentials.custom_data)
                real_ib_account_id = service_data.get("ib_account_id")
                
                if real_ib_account_id:
                    logger.info(f"Using real IB account ID: {real_ib_account_id} for account {account.account_id}")
                    return real_ib_account_id
                else:
                    logger.warning(f"No real IB account ID found in custom_data for account {account.account_id}")
            else:
                logger.warning(f"No credentials or custom_data found for account {account.account_id}")
            
            return None
        except Exception as e:
            logger.error(f"Error extracting real IB account ID: {str(e)}")
            return None

    async def __del__(self):
        """Cleanup HTTP client on deletion"""
        if hasattr(self, 'http_client'):
            await self.http_client.aclose()