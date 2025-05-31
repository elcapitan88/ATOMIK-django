from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from datetime import datetime
from .base import BaseBroker
from .config import BrokerConfig, BrokerEnvironment

from ...models.broker import BrokerAccount, BrokerCredentials

class BaseBrokerInterface(ABC):
    """Abstract base class for broker implementations"""
    
    @abstractmethod
    async def authenticate(self, credentials: BrokerCredentials) -> bool:
        """Authenticate with the broker"""
        pass
        
    @abstractmethod
    async def connect_account(self, account_id: str, credentials: Dict[str, Any]) -> BrokerAccount:
        """Connect to a trading account"""
        pass
        
    @abstractmethod
    async def disconnect_account(self, account_id: str) -> bool:
        """Disconnect a trading account"""
        pass
        
    @abstractmethod
    async def get_account_positions(self, account_id: str) -> List[Dict[str, Any]]:
        """Get account positions"""
        pass
        
    @abstractmethod
    async def place_order(self, account_id: str, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Place a trading order"""
        pass

    @abstractmethod
    async def cancel_order(self, account_id: str, order_id: str) -> bool:
        """Cancel an order"""
        pass

__all__ = ['BaseBroker', 'BrokerConfig', 'BrokerEnvironment']