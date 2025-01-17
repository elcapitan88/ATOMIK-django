from enum import Enum

# API Endpoints and URLs
TRADOVATE_DEMO_EXCHANGE_URL = 'https://demo.tradovateapi.com/auth/oauthtoken'
TRADOVATE_LIVE_EXCHANGE_URL = 'https://live.tradovateapi.com/auth/oauthtoken'

TRADOVATE_DEMO_API_URL = 'https://demo.tradovateapi.com/v1'
TRADOVATE_LIVE_API_URL = 'https://live.tradovateapi.com/v1'

TRADOVATE_DEMO_WS_URL = 'wss://demo.tradovateapi.com/v1/websocket'
TRADOVATE_LIVE_WS_URL = 'wss://live.tradovateapi.com/v1/websocket'

# Authentication
class AuthEndpoints:
    OAUTH_TOKEN = '/auth/oauthtoken'
    ACCESS_TOKEN = '/auth/accesstokenrequest'
    REFRESH_TOKEN = '/auth/refresh'
    REVOKE_TOKEN = '/auth/revoke'

# Account Endpoints
class AccountEndpoints:
    LIST = '/account/list'
    ITEM = '/account/item'
    FIND = '/account/find'
    SUGGEST = '/account/suggest'
    POSITIONS = '/account/positions'
    RISK_STATEMENT = '/account/riskstatement'
    CASH_BALANCE = '/cashBalance/list'

# Order Endpoints
class OrderEndpoints:
    PLACE_ORDER = '/order/placeorder'
    MODIFY_ORDER = '/order/modifyorder'
    CANCEL_ORDER = '/order/cancelorder'
    LIST = '/order/list'
    ITEM = '/order/item'
    FIND = '/order/find'
    DEPENDENTS = '/order/deps'
    LIQUIDATE = '/order/liquidateposition'
    MASS_CANCEL = '/order/masscancelorders'

# Position Endpoints
class PositionEndpoints:
    LIST = '/position/list'
    ITEM = '/position/item'
    FIND = '/position/find'
    SUGGEST = '/position/suggest'
    DEPS = '/position/deps'

# Contract Endpoints
class ContractEndpoints:
    LIST = '/contract/list'
    ITEM = '/contract/item'
    FIND = '/contract/find'
    SUGGEST = '/contract/suggest'
    DEPS = '/contract/deps'

# Order Types
class OrderType(Enum):
    MARKET = 'Market'
    LIMIT = 'Limit'
    STOP_MARKET = 'StopMarket'
    STOP_LIMIT = 'StopLimit'
    MIT = 'MIT'  # Market if touched
    LIT = 'LIT'  # Limit if touched

# Order Status
class OrderStatus(Enum):
    ACCEPTED = 'Accepted'
    CANCELLED = 'Cancelled'
    COMPLETED = 'Completed'
    FILLED = 'Filled'
    PENDING = 'Pending'
    REJECTED = 'Rejected'
    WORKING = 'Working'
    EXPIRED = 'Expired'

# Time in Force
class TimeInForce(Enum):
    DAY = 'Day'
    GTC = 'GTC'  # Good Till Cancelled
    GTD = 'GTD'  # Good Till Date
    FOK = 'FOK'  # Fill or Kill
    IOC = 'IOC'  # Immediate or Cancel

# Action Types
class ActionType(Enum):
    BUY = 'Buy'
    SELL = 'Sell'

# Account Types
class AccountType(Enum):
    LIVE = 'Live'
    DEMO = 'Demo'

# WebSocket Message Types
class WebSocketMessageType(Enum):
    HEARTBEAT = 'heartbeat'
    DOM = 'dom'  # Depth of Market
    TRADE = 'trade'
    POSITION = 'position'
    ORDER = 'order'
    FILL = 'fill'
    ACCOUNT = 'account'
    ERROR = 'error'

# WebSocket Subscription Types
class SubscriptionType(Enum):
    QUOTES = 'md/subscribeQuote'
    TRADES = 'md/subscribeTrade'
    DOM = 'md/subscribeDOM'
    CHARTS = 'md/subscribeChart'

# Error Codes
class ErrorCodes:
    INVALID_TOKEN = 'InvalidToken'
    TOKEN_EXPIRED = 'TokenExpired'
    INSUFFICIENT_FUNDS = 'InsufficientFunds'
    INVALID_ORDER = 'InvalidOrder'
    RATE_LIMIT_EXCEEDED = 'RateLimitExceeded'
    MARKET_CLOSED = 'MarketClosed'
    INVALID_SYMBOL = 'InvalidSymbol'
    INVALID_ACCOUNT = 'InvalidAccount'
    CONNECTION_ERROR = 'ConnectionError'

# Rate Limits
RATE_LIMITS = {
    'orders': {
        'max_per_second': 5,
        'max_per_minute': 100
    },
    'positions': {
        'max_per_second': 10,
        'max_per_minute': 200
    },
    'accounts': {
        'max_per_second': 2,
        'max_per_minute': 50
    }
}

# Timeouts (in seconds)
TIMEOUTS = {
    'connect': 30,
    'read': 30,
    'write': 30,
    'auth': 45,
    'ws_connect': 30,
    'ws_response': 10
}

# Market Hours (UTC)
MARKET_HOURS = {
    'pre_market_start': '09:30',
    'market_open': '14:30',
    'market_close': '21:00',
    'post_market_end': '22:00'
}

# Retry Configuration
RETRY_CONFIG = {
    'max_retries': 3,
    'base_delay': 1,  # seconds
    'max_delay': 60,  # seconds
    'exponential_base': 2
}

# Websocket Configuration
WEBSOCKET_CONFIG = {
    'ping_interval': 15,  # seconds
    'ping_timeout': 10,  # seconds
    'close_timeout': 5,  # seconds
    'max_message_size': 1024 * 1024,  # 1MB
    'compression': None
}

# Contract Specifications
CONTRACT_SPECS = {
    'ES': {
        'symbol': 'ES',
        'name': 'E-mini S&P 500',
        'tick_size': 0.25,
        'value_per_tick': 12.50,
        'margin_day': 500.00,
        'margin_overnight': 11000.00
    },
    'NQ': {
        'symbol': 'NQ',
        'name': 'E-mini NASDAQ-100',
        'tick_size': 0.25,
        'value_per_tick': 5.00,
        'margin_day': 500.00,
        'margin_overnight': 9900.00
    },
    'MES': {
        'symbol': 'MES',
        'name': 'Micro E-mini S&P 500',
        'tick_size': 0.25,
        'value_per_tick': 1.25,
        'margin_day': 50.00,
        'margin_overnight': 1100.00
    },
    'MNQ': {
        'symbol': 'MNQ',
        'name': 'Micro E-mini NASDAQ-100',
        'tick_size': 0.25,
        'value_per_tick': 0.50,
        'margin_day': 50.00,
        'margin_overnight': 990.00
    }
}

KNOWN_CONTRACTS = {
    '3594446': 'MNQZ4',  # MNQ December 2024
    '3138191': 'NQZ4',   # NQ December 2024
    '3594447': 'MESZ4',  # Micro E-mini S&P 500 December 2024
}