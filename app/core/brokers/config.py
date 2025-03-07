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
    )
    # Add more brokers as needed
}