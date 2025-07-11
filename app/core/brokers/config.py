from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel


class ApiEndpointConfig(BaseModel):
    base: str
    websocket: str

class BrokerEnvironment(str, Enum):
    DEMO = "demo"
    LIVE = "live"
    PAPER = "paper"

class ConnectionMethod(str, Enum):
    OAUTH = "oauth"
    API_KEY = "api_key"
    CREDENTIALS = "credentials"

class BrokerFeatures(BaseModel):
    """Features supported by the broker"""
    real_time_data: bool = False
    market_data_delay: int = 0  # Delay in seconds for market data
    supports_websocket: bool = False
    supported_order_types: List[str] = []
    max_positions: Optional[int] = None
    supports_multiple_accounts: bool = False
    supported_assets: List[str] = []

class BrokerConfig(BaseModel):
    """Configuration for a broker"""
    id: str
    name: str
    description: str
    environments: List[BrokerEnvironment]
    connection_method: ConnectionMethod
    features: BrokerFeatures
    oauth_config: Optional[Dict] = None
    api_endpoints: Dict[str, ApiEndpointConfig] 
    logo_url: Optional[str] = None
    docs_url: Optional[str] = None



class TokenConfig:
    """Token configuration settings"""
    # Class-level constants for global settings
    REFRESH_INTERVAL = 120  # Changed from 30 to 120 seconds
    ALERT_THRESHOLD = 5  # Alert after 5 failed refresh attempts

    # Broker-specific token configurations
    BROKER_TOKEN_CONFIGS = {
        'tradovate': {
            'TOKEN_LIFETIME': 4800,  # 80 minutes (actual Tradovate time)
            'REFRESH_THRESHOLD': 0.5625,  # Refresh at ~26.4 minutes remaining
            'MAX_RETRY_ATTEMPTS': 3,
            'RETRY_DELAY': 10,  # Seconds between retry attempts
            'SUPPORTS_REFRESH_TOKEN': False  # Explicit flag showing we only use access token
        },
        'binance': {
            'TOKEN_LIFETIME': 31536000,  # 1 year (API keys don't expire)
            'REFRESH_THRESHOLD': 0.9,  # Don't refresh unless really necessary
            'MAX_RETRY_ATTEMPTS': 3,
            'RETRY_DELAY': 5,  # Seconds between retry attempts
            'SUPPORTS_REFRESH_TOKEN': False  # API keys don't use refresh tokens
        },
        'binanceus': {
            'TOKEN_LIFETIME': 31536000,  # 1 year (API keys don't expire)
            'REFRESH_THRESHOLD': 0.9,  # Don't refresh unless really necessary
            'MAX_RETRY_ATTEMPTS': 3,
            'RETRY_DELAY': 5,  # Seconds between retry attempts
            'SUPPORTS_REFRESH_TOKEN': False  # API keys don't use refresh tokens
        }
    }

    @classmethod
    def get_broker_config(cls, broker_id: str) -> dict:
        """Get token configuration for specific broker"""
        return cls.BROKER_TOKEN_CONFIGS.get(broker_id, {
            'TOKEN_LIFETIME': 4800,  # Default values if broker not found
            'REFRESH_THRESHOLD': 0.5625,
            'MAX_RETRY_ATTEMPTS': 3,
            'RETRY_DELAY': 10
        })

# Broker configurations
BROKER_CONFIGS = {
    "tradovate": BrokerConfig(
        id="tradovate",
        name="Tradovate",
        description="Tradovate Futures Trading",
        environments=[BrokerEnvironment.DEMO, BrokerEnvironment.LIVE],
        connection_method=ConnectionMethod.OAUTH,
        features=BrokerFeatures(
            real_time_data=True,
            supports_websocket=True,
            supported_order_types=["MARKET", "LIMIT", "STOP", "STOP_LIMIT"],
            supports_multiple_accounts=True,
            supported_assets=["ES", "NQ", "CL", "GC", "SI", "ZB", "RTY", "YM"]
        ),
        oauth_config={
            "client_id_env": "TRADOVATE_CLIENT_ID",
            "client_secret_env": "TRADOVATE_CLIENT_SECRET",
            "scope": "trading",
            "auth_url_template": "{environment}.tradovate.com/oauth/authorize",
            "token_url_template": "{environment}.tradovate.com/oauth/token"
        },
        api_endpoints={
            "demo": ApiEndpointConfig(
                base="https://demo.tradovateapi.com/v1",
                websocket="wss://demo.tradovateapi.com/v1/websocket"
            ),
            "live": ApiEndpointConfig(
                base="https://live.tradovateapi.com/v1",
                websocket="wss://live.tradovateapi.com/v1/websocket"
            )
        }
    ),
    
    "binance": BrokerConfig(
        id="binance",
        name="Binance",
        description="Binance Global - Crypto Exchange",
        environments=[BrokerEnvironment.LIVE],
        connection_method=ConnectionMethod.API_KEY,
        features=BrokerFeatures(
            real_time_data=True,
            supports_websocket=True,
            supported_order_types=["MARKET", "LIMIT", "STOP_LOSS", "STOP_LOSS_LIMIT", "TAKE_PROFIT", "TAKE_PROFIT_LIMIT"],
            supports_multiple_accounts=False,
            supported_assets=["SPOT", "FUTURES"]
        ),
        api_endpoints={
            "live": ApiEndpointConfig(
                base="https://api.binance.com",
                websocket="wss://stream.binance.com:9443"
            )
        },
        logo_url="/logos/binance.svg",
        docs_url="https://binance-docs.github.io/apidocs/spot/en/"
    ),
    
    "binanceus": BrokerConfig(
        id="binanceus",
        name="Binance.US",
        description="Binance US - Crypto Exchange",
        environments=[BrokerEnvironment.LIVE],
        connection_method=ConnectionMethod.API_KEY,
        features=BrokerFeatures(
            real_time_data=True,
            supports_websocket=True,
            supported_order_types=["MARKET", "LIMIT", "STOP_LOSS", "STOP_LOSS_LIMIT"],
            supports_multiple_accounts=False,
            supported_assets=["SPOT"]
        ),
        api_endpoints={
            "live": ApiEndpointConfig(
                base="https://api.binance.us",
                websocket="wss://stream.binance.us:9443"
            )
        },
        logo_url="/logos/binance-us.svg",
        docs_url="https://docs.binance.us/"
    )
    # Add more brokers as needed
}