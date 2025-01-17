# strategies/brokers/tradovate/apps.py

from django.apps import AppConfig

class TradovateConfig(AppConfig):
    """
    Configuration class for the Tradovate integration.
    """
    name = 'strategies.brokers.tradovate'
    label = 'strategies_tradovate'
    verbose_name = 'Tradovate Integration'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        """
        Perform initialization when the app is ready.
        Sets up basic broker configuration.
        """
        # Initialize WebSocket configuration
        from django.conf import settings
        if not hasattr(settings, 'TRADOVATE_WEBSOCKET_CONFIG'):
            settings.TRADOVATE_WEBSOCKET_CONFIG = {
                'heartbeat_interval': 15,  # seconds
                'reconnect_interval': 1,   # seconds
                'max_reconnect_attempts': 5,
                'message_buffer_size': 1000,
            }