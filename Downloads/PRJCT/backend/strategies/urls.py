from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from .views.webhook_views import (
    generate_webhook,
    list_webhooks,
    delete_webhook,
    webhook_endpoint,
    webhook_details,
    list_webhook_logs,
    webhook_statistics,
    test_webhook,
    clear_webhook_logs
)
from .views.strategy_views import (
    activate_strategy,
    list_strategies,
    toggle_strategy,
    delete_strategy
)

app_name = 'strategies'

# Strategy-related URL patterns
strategy_patterns = [
    path('strategies/list/', list_strategies, name='list_strategies'),
    path('strategies/activate/', activate_strategy, name='activate_strategy'),
    path('strategies/toggle/<int:strategy_id>/', toggle_strategy, name='toggle_strategy'),
    path('strategies/delete/<int:strategy_id>/', delete_strategy, name='delete_strategy'),
]

# Webhook-related URL patterns
webhook_patterns = [
    # Generate and list webhooks
    path('webhooks/generate/', generate_webhook, name='generate_webhook'),
    path('webhooks/list/', list_webhooks, name='list_webhooks'),
    path('webhook/<uuid:token>/', webhook_endpoint, name='webhook_endpoint'),
    # Main webhook operations
    path('webhooks/<uuid:token>/', delete_webhook, name='delete_webhook'),  # Changed this line
    
    
    # Additional webhook operations
    path('webhooks/<uuid:token>/details/', webhook_details, name='webhook_details'),
    path('webhooks/<uuid:token>/logs/', list_webhook_logs, name='webhook_logs'),
    path('webhooks/<uuid:token>/stats/', webhook_statistics, name='webhook_statistics'),
    path('webhooks/<uuid:token>/test/', test_webhook, name='test_webhook'),
    path('webhooks/<uuid:token>/clear-logs/', clear_webhook_logs, name='clear_webhook_logs'),
]

# Combine all URL patterns
urlpatterns = strategy_patterns + webhook_patterns