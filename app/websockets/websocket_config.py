# app/websockets/websocket_config.py

class WebSocketConfig:
    HEARTBEAT = {
        'INTERVAL': 15000,        # 15 seconds
        'TIMEOUT': 5000,          # 5 seconds
        'MAX_MISSED': 3,          # Max missed heartbeats before disconnect
        'CLEANUP_INTERVAL': 60000, # Dead connection cleanup interval
        'RECONNECT_BACKOFF': {
            'INITIAL': 1000,      # Initial backoff 1 second
            'FACTOR': 2,          # Exponential factor
            'MAX': 30000          # Max 30 seconds
        }
    }

    METRICS = {
        'ENABLE_LOGGING': True,
        'RETENTION_DAYS': 7
    }

    LOGGING = {
        'HEARTBEAT_DEBUG': True,  # Enable detailed heartbeat logging
        'MESSAGE_DEBUG': True     # Enable detailed message logging
    }