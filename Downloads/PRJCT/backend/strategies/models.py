from django.db import models
from django.conf import settings
from django.utils import timezone
import uuid
import secrets
import hmac
import hashlib
from collections import defaultdict
import threading
import base64
from typing import Optional
from datetime import timedelta

class Broker(models.Model):
    """Model representing trading brokers."""
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']

class BrokerAccount(models.Model):
    """Model representing a broker trading account."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    broker = models.ForeignKey(Broker, on_delete=models.CASCADE)
    account_id = models.CharField(max_length=100)
    nickname = models.CharField(max_length=100, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    environment = models.CharField(
        max_length=10,
        choices=[('live', 'Live'), ('demo', 'Demo')],
        default='demo'
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('broker', 'account_id')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.broker.name} - {self.nickname or self.account_id}"

class Webhook(models.Model):
    """Model for storing and managing webhook configurations."""
    
    SOURCE_CHOICES = [
        ('tradingview', 'TradingView'),
        ('trendspider', 'TrendSpider'),
        ('custom', 'Custom')
    ]

    # Class-level rate limiting storage
    _rate_limits = defaultdict(list)
    _rate_limit_lock = threading.Lock()

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='webhooks'
    )
    token = models.UUIDField(
        default=uuid.uuid4, 
        editable=False, 
        unique=True
    )
    secret_key = models.CharField(
        max_length=64,
        default=secrets.token_hex,
        help_text="Secret key for signing webhook payloads"
    )
    name = models.CharField(max_length=255, blank=True, null=True)
    details = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    last_triggered = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    source_type = models.CharField(
        max_length=50,
        choices=SOURCE_CHOICES,
        default='custom'
    )
    allowed_ips = models.TextField(
        blank=True,
        null=True,
        help_text="Comma-separated list of allowed IP addresses"
    )
    max_triggers_per_minute = models.IntegerField(default=60)
    require_signature = models.BooleanField(default=True)
    max_retries = models.IntegerField(default=3)
    retry_interval = models.IntegerField(default=60)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['token']),
        ]

    def __str__(self):
        return f"{self.name or 'Unnamed Webhook'} ({self.token})"

    def get_webhook_url_with_hmac(self) -> str:
        """Get webhook URL with authentication parameters."""
        base_url = getattr(settings, 'BASE_URL', 'http://localhost:8000')
        webhook_url = f"{base_url}/api/webhook/{self.token}/?secret={self.secret_key}"
        return webhook_url

    def generate_signature(self, payload: str) -> str:
        """Generate HMAC signature for payload verification."""
        hmac_obj = hmac.new(
            key=self.secret_key.encode(),
            msg=payload.encode(),
            digestmod=hashlib.sha256
        )
        return hmac_obj.hexdigest()

    def verify_signature(self, payload: str, signature: str) -> bool:
        """Verify the HMAC signature of a payload."""
        expected_signature = self.generate_signature(payload)
        return hmac.compare_digest(expected_signature, signature)

    def verify_ip(self, client_ip: str) -> bool:
        """Verify if the client IP is allowed."""
        if not self.allowed_ips:
            return True
        allowed_ips = [ip.strip() for ip in self.allowed_ips.split(',')]
        return client_ip in allowed_ips

    def check_rate_limit(self) -> bool:
        """Check if the webhook has exceeded its rate limit."""
        now = timezone.now()
        minute_ago = now - timezone.timedelta(minutes=1)
        
        with self._rate_limit_lock:
            self._rate_limits[self.token] = [
                timestamp for timestamp in self._rate_limits[self.token]
                if timestamp > minute_ago
            ]
            
            if len(self._rate_limits[self.token]) >= self.max_triggers_per_minute:
                return False
                
            self._rate_limits[self.token].append(now)
            return True

    def log_trigger(self, success: bool, payload: str, error_message: Optional[str] = None) -> None:
        """Log a webhook trigger event."""
        WebhookLog.objects.create(
            webhook=self,
            success=success,
            payload=payload,
            error_message=error_message
        )

        if success:
            self.last_triggered = timezone.now()
            self.save(update_fields=['last_triggered'])

class WebhookLog(models.Model):
    """Model for logging webhook triggers and responses."""
    webhook = models.ForeignKey(
        Webhook, 
        on_delete=models.CASCADE, 
        related_name='logs'
    )
    triggered_at = models.DateTimeField(default=timezone.now)
    success = models.BooleanField(default=True)
    payload = models.TextField()
    error_message = models.TextField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True)
    processing_time = models.FloatField(
        null=True,
        help_text="Processing time in seconds"
    )

    class Meta:
        indexes = [
            models.Index(fields=['webhook', 'triggered_at']),
            models.Index(fields=['success']),
        ]
        ordering = ['-triggered_at']

    def __str__(self):
        status = "Success" if self.success else "Failed"
        return f"{status} - {self.webhook.name} ({self.triggered_at})"

class ActivatedStrategy(models.Model):
    """Model for storing activated trading strategies."""
    
    STRATEGY_TYPES = [
        ('single', 'Single Account'),
        ('multiple', 'Multiple Account')
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='strategies'
    )
    strategy_type = models.CharField(
        max_length=20,
        choices=STRATEGY_TYPES,
        default='single'
    )
    webhook_id = models.UUIDField()
    account_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Account ID for single account strategy"
    )
    leader_account_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Leader account ID for group strategy"
    )
    follower_accounts = models.ManyToManyField(
        BrokerAccount,
        related_name='following_strategies',
        blank=True
    )
    quantity = models.IntegerField(
        null=True,
        blank=True,
        help_text="Trade quantity for single account"
    )
    leader_quantity = models.IntegerField(
        null=True,
        blank=True,
        help_text="Trade quantity for leader account"
    )
    follower_quantity = models.IntegerField(
        null=True,
        blank=True,
        help_text="Trade quantity for follower accounts"
    )
    ticker = models.CharField(
        max_length=10,
        help_text="Trading symbol"
    )
    group_name = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Name for group strategy"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    last_triggered = models.DateTimeField(null=True, blank=True)
    total_trades = models.IntegerField(default=0)
    successful_trades = models.IntegerField(default=0)
    failed_trades = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Activated Strategy"
        verbose_name_plural = "Activated Strategies"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['webhook_id']),
        ]

    def __str__(self):
        if self.strategy_type == 'single':
            return f"Single Account Strategy - {self.ticker}"
        return f"Group Strategy - {self.group_name}"