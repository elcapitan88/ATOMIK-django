from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import logging
import base64
import json
import uuid
from sqlalchemy.orm import Session
from fastapi import HTTPException

from ...models.broker import BrokerAccount, BrokerCredentials
from ...models.user import User
from ...core.config import settings
from .config import BrokerConfig, BrokerEnvironment

logger = logging.getLogger(__name__)

class BrokerException(Exception):
    """Base exception for broker-related errors"""
    pass

class AuthenticationError(BrokerException):
    """Authentication-related errors"""
    pass

class ConnectionError(BrokerException):
    """Connection-related errors"""
    pass

class OrderError(BrokerException):
    """Order-related errors"""
    pass

class BaseBroker(ABC):
    """
    Base class for all broker implementations.
    Each broker must implement these methods to ensure consistent behavior.
    """

    def __init__(self, broker_id: str, db: Session):
        self.broker_id = broker_id
        self.db = db
        self.config = self._load_config()

    def _load_config(self) -> BrokerConfig:
        """Load broker configuration"""
        from .config import BROKER_CONFIGS
        config = BROKER_CONFIGS.get(self.broker_id)
        if not config:
            raise ValueError(f"No configuration found for broker: {self.broker_id}")
        return config

    # Core Abstract Methods
    @abstractmethod
    async def authenticate(self, credentials: Dict[str, Any]) -> BrokerCredentials:
        """Authenticate with the broker"""
        pass

    @abstractmethod
    async def validate_credentials(self, credentials: BrokerCredentials) -> bool:
        """Validate stored credentials"""
        pass

    @abstractmethod
    async def refresh_credentials(self, credentials: BrokerCredentials) -> BrokerCredentials:
        """Refresh authentication credentials"""
        pass

    @abstractmethod
    async def connect_account(
        self,
        user: User,
        account_id: str,
        environment: BrokerEnvironment,
        credentials: Optional[Dict[str, Any]] = None
    ) -> BrokerAccount:
        """Connect to a trading account"""
        pass

    @abstractmethod
    async def disconnect_account(self, account: BrokerAccount) -> bool:
        """Disconnect a trading account"""
        pass

    @abstractmethod
    async def fetch_accounts(self, user: User) -> List[Dict[str, Any]]:
        """Fetch all accounts for a given user from this broker"""
        pass

    # Account Information Methods
    @abstractmethod
    async def get_account_status(self, account: BrokerAccount) -> Dict[str, Any]:
        """Get account status and information"""
        pass

    @abstractmethod
    async def get_positions(self, account: BrokerAccount) -> List[Dict[str, Any]]:
        """Get current positions for an account"""
        pass

    @abstractmethod
    async def get_orders(self, account: BrokerAccount) -> List[Dict[str, Any]]:
        """Get orders for an account"""
        pass

    # Order Management Methods
    @abstractmethod
    async def place_order(
        self,
        account: BrokerAccount,
        order_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Place a trading order"""
        pass

    @abstractmethod
    async def cancel_order(
        self,
        account: BrokerAccount,
        order_id: str
    ) -> bool:
        """Cancel an order"""
        pass

    # Connection Initialization Methods
    @abstractmethod
    async def initialize_oauth(
        self,
        user: User,
        environment: str
    ) -> Dict[str, Any]:
        """Initialize OAuth flow"""
        pass

    @abstractmethod
    async def initialize_api_key(
        self,
        user: User,
        environment: str,
        credentials: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Initialize API key connection"""
        pass

    # Utility Methods
    async def initialize_connection(
        self,
        user: User,
        environment: str,
        credentials: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Initialize broker connection based on credentials type"""
        try:
            if not await self.validate_environment(environment):
                raise ValueError(f"Invalid environment: {environment}")

            existing = await self.check_account_exists(
                user.id, 
                credentials.get('account_id'), 
                environment
            )
            
            if existing and existing.is_active:
                raise ConnectionError("Account already connected")

            if credentials['type'] == 'oauth':
                return await self.initialize_oauth(user, environment)
            elif credentials['type'] == 'api_key':
                return await self.initialize_api_key(user, environment, credentials)
            else:
                raise ValueError(f"Unsupported credential type: {credentials['type']}")

        except Exception as e:
            logger.error(f"Connection initialization failed: {str(e)}")
            raise

    async def validate_environment(self, environment: str) -> bool:
        """Validate if environment is supported by broker"""
        return BrokerEnvironment(environment) in self.config.environments

    async def check_account_exists(
        self,
        user_id: int,
        account_id: str,
        environment: str
    ) -> Optional[BrokerAccount]:
        """Check if account already exists for user"""
        return self.db.query(BrokerAccount).filter(
            BrokerAccount.user_id == user_id,
            BrokerAccount.broker_id == self.broker_id,
            BrokerAccount.account_id == account_id,
            BrokerAccount.environment == environment
        ).first()

    # Response Normalization Methods
    def normalize_order_response(self, raw_response: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize broker-specific order response to standard format"""
        return {
            "order_id": str(raw_response.get("orderId", "")),
            "status": raw_response.get("status", "unknown"),
            "symbol": raw_response.get("symbol", ""),
            "side": raw_response.get("side", ""),
            "quantity": float(raw_response.get("quantity", 0)),
            "filled_quantity": float(raw_response.get("filledQuantity", 0)),
            "price": float(raw_response.get("price", 0)),
            "created_at": raw_response.get("timestamp", datetime.utcnow().isoformat()),
        }

    def normalize_position_response(self, raw_response: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize broker-specific position response to standard format"""
        return {
            "symbol": raw_response.get("symbol", ""),
            "side": raw_response.get("side", ""),
            "quantity": float(raw_response.get("quantity", 0)),
            "entry_price": float(raw_response.get("entryPrice", 0)),
            "current_price": float(raw_response.get("currentPrice", 0)),
            "unrealized_pnl": float(raw_response.get("unrealizedPnL", 0)),
            "realized_pnl": float(raw_response.get("realizedPnL", 0)),
            "updated_at": raw_response.get("timestamp", datetime.utcnow().isoformat()),
        }

    # State Token Management Methods
    def generate_state_token(self, user_id: int, environment: str) -> str:
        """Generate state token for OAuth flow"""
        state_data = {
            'user_id': user_id,
            'environment': environment,
            'timestamp': datetime.utcnow().isoformat(),
            'nonce': str(uuid.uuid4())
        }
        return base64.urlsafe_b64encode(json.dumps(state_data).encode()).decode()

    def verify_state_token(self, state: str) -> Dict[str, Any]:
        """Verify and decode state token"""
        try:
            state = state.replace(' ', '+')
            if '%3D' in state:
                state = state.replace('%3D', '=')
            padding = 4 - (len(state) % 4)
            if padding != 4:
                state = state + ('=' * padding)

            decoded_data = json.loads(base64.urlsafe_b64decode(state).decode())
            
            timestamp = datetime.fromisoformat(decoded_data['timestamp'])
            if (datetime.utcnow() - timestamp).total_seconds() > 900:
                raise ValueError("State token expired")

            return decoded_data

        except Exception as e:
            logger.error(f"State token verification failed: {str(e)}")
            raise ValueError("Invalid state token")

    # Error Logging Methods
    async def log_error(
        self,
        error_type: str,
        error_message: str,
        account_id: Optional[str] = None
    ) -> None:
        """Log broker-specific errors"""
        logger.error(
            f"Broker {self.broker_id} error: {error_type} - {error_message} "
            f"(Account: {account_id or 'N/A'})"
        )

    # Broker Instance Factory Method
    @staticmethod
    def get_broker_instance(broker_id: str, db: Session) -> 'BaseBroker':
        """Factory method to get broker implementation"""
        try:
            from .implementations.tradovate import TradovateBroker
            from .implementations.binance import BinanceBroker
            
            broker_implementations = {
                "tradovate": TradovateBroker,
                "binance": BinanceBroker,
                "binanceus": BinanceBroker,
            }

            broker_class = broker_implementations.get(broker_id)
            if not broker_class:
                raise ValueError(f"No implementation found for broker: {broker_id}")

            return broker_class(broker_id, db)
            
        except ImportError as e:
            logger.error(f"Failed to import broker implementation: {str(e)}")
            raise ImportError(f"Could not import broker implementation for {broker_id}: {str(e)}")