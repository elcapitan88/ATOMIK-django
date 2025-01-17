# routing.py
from django.urls import re_path
from .brokers.tradovate.consumers import TradovateConsumer

websocket_urlpatterns = [
    re_path(
        r'ws/tradovate/(?P<account_id>[^/]+)/$', 
        TradovateConsumer.as_asgi()
    ),
]