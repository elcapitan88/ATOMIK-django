"""
Application WebSocket Configuration

Configuration settings for the Application WebSocket system (chat, notifications, UI events).
Adapted from trading WebSocket but focused on application features.
"""


class AppWebSocketConfig:
    """Configuration for Application WebSocket system"""
    
    HEARTBEAT = {
        'INTERVAL': 30000,        # 30 seconds (less frequent than trading)
        'TIMEOUT': 5000,          # 5 seconds
        'MAX_MISSED': 3,          # Max missed heartbeats before disconnect
        'CLEANUP_INTERVAL': 60000, # Dead connection cleanup interval
        'RECONNECT_BACKOFF': {
            'INITIAL': 1000,      # Initial backoff 1 second
            'FACTOR': 2,          # Exponential factor
            'MAX': 30000          # Max 30 seconds
        }
    }

    CHAT = {
        'MAX_MESSAGE_LENGTH': 2000,     # Max characters per message
        'MAX_MESSAGES_PER_MINUTE': 30,  # Rate limiting
        'TYPING_TIMEOUT': 3000,         # Typing indicator timeout (ms)
        'REACTION_LIMIT': 50,           # Max reactions per message
    }

    CONNECTION = {
        'MAX_CONNECTIONS_PER_USER': 3,  # Multiple tabs/devices
        'IDLE_TIMEOUT': 300000,         # 5 minutes idle timeout
        'MAX_CHANNELS_PER_USER': 50,    # Channel subscription limit
    }

    METRICS = {
        'ENABLE_LOGGING': True,
        'RETENTION_DAYS': 7,
        'STATS_UPDATE_INTERVAL': 60,    # Update stats every minute
    }

    LOGGING = {
        'HEARTBEAT_DEBUG': False,       # Less verbose for application WebSocket
        'MESSAGE_DEBUG': True,          # Enable chat message logging
        'CONNECTION_DEBUG': True,       # Enable connection logging
    }