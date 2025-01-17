from django.db import models
from django.conf import settings
from django.utils import timezone
from typing import Optional
from datetime import timedelta, datetime
from ..base.interfaces import TokenRefreshMixin

class TradovateAccount(models.Model):
    """Model representing a Tradovate trading account."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE,
        related_name='tradovate_accounts'
    )
    broker = models.ForeignKey(
        'strategies.Broker',  # Reference to the main Broker model
        on_delete=models.CASCADE,
        related_name='tradovate_accounts'
    )
    account_id = models.CharField(max_length=100)
    name = models.CharField(max_length=200, default="Tradovate Account")
    nickname = models.CharField(max_length=100, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    environment = models.CharField(
        max_length=10,
        choices=[('live', 'Live'), ('demo', 'Demo')],
        default='demo'
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    last_connected = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=[
            ('active', 'Active'),
            ('inactive', 'Inactive'),
            ('connecting', 'Connecting'),
            ('error', 'Error')
        ],
        default='inactive'
    )
    error_message = models.TextField(blank=True, null=True)
    balance = models.DecimalField(
        max_digits=15, 
        decimal_places=2, 
        null=True, 
        blank=True
    )
    margin_used = models.DecimalField(
        max_digits=15, 
        decimal_places=2, 
        null=True, 
        blank=True
    )
    available_margin = models.DecimalField(
        max_digits=15, 
        decimal_places=2, 
        null=True, 
        blank=True
    )
    day_pnl = models.DecimalField(
        max_digits=15, 
        decimal_places=2, 
        null=True, 
        blank=True
    )

    class Meta:
        app_label = 'strategies_tradovate'
        unique_together = ('broker', 'account_id')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.nickname or self.name} ({self.environment})"

class TradovateToken(TokenRefreshMixin, models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE,
        related_name='tradovate_tokens'
    )
    access_token = models.TextField()
    refresh_token = models.TextField()
    md_access_token = models.TextField(null=True, blank=True)
    expires_in = models.IntegerField(default=4800)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    last_refreshed = models.DateTimeField(null=True, blank=True)
    is_valid = models.BooleanField(default=True)
    environment = models.CharField(
        max_length=10,
        choices=[('live', 'Live'), ('demo', 'Demo')],
        default='demo'
    )

    class Meta:
        unique_together = [('user', 'environment')]
        ordering = ['-created_at']

    def refresh_token(self):
        """Implement Tradovate-specific token refresh"""
        try:
            from .views import refresh_tradovate_token
            return refresh_tradovate_token(self)
        except Exception as e:
            logger.error(f"Failed to refresh Tradovate token: {str(e)}")
            self.is_valid = False
            self.save()
            return False

    def is_token_expired(self) -> bool:
        if not self.is_valid:
            return True
        
        if not self.last_refreshed:
            return True

        expiry_time = self.last_refreshed + timedelta(seconds=self.expires_in)
        # Refresh when 90% of the time has passed
        buffer_time = timedelta(seconds=self.expires_in * 0.1)
        return timezone.now() > (expiry_time - buffer_time)

    def get_token_expiry(self) -> Optional[datetime]:
        if not self.last_refreshed:
            return None
        return self.last_refreshed + timedelta(seconds=self.expires_in)

    def __str__(self):
        return f"Token for {self.user.username} ({self.environment})"


class TradovateOrder(models.Model):
    """Model for tracking Tradovate orders."""
    account = models.ForeignKey(
        TradovateAccount,
        on_delete=models.CASCADE,
        related_name='orders'
    )
    strategy = models.ForeignKey(
        'strategies.ActivatedStrategy',
        on_delete=models.CASCADE,
        related_name='tradovate_orders'
    )
    tradovate_order_id = models.CharField(max_length=100)
    webhook_id = models.UUIDField()
    order_type = models.CharField(max_length=20)
    action = models.CharField(max_length=10)
    symbol = models.CharField(max_length=20)
    quantity = models.IntegerField()
    price = models.DecimalField(
        max_digits=15,
        decimal_places=4,
        null=True,
        blank=True
    )
    status = models.CharField(max_length=20)
    raw_request = models.JSONField()
    raw_response = models.JSONField()
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'strategies_tradovate'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.action} {self.quantity} {self.symbol} ({self.status})"