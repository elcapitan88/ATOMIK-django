from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from strategies.brokers.tradovate.models import TradovateToken
from strategies.brokers.tradovate.views import refresh_tradovate_token
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Refresh Tradovate tokens that are about to expire'

    def handle(self, *args, **options):
        tokens_to_refresh = TradovateToken.objects.filter(
            last_refreshed__lte=timezone.now() - timedelta(minutes=55)
        )
        
        for token in tokens_to_refresh:
            try:
                refresh_tradovate_token(token)
                self.stdout.write(self.style.SUCCESS(f'Successfully refreshed token for user {token.user.username}'))
                logger.info(f'Token refreshed for user {token.user.username}')
            except Exception as e:
                error_message = f'Failed to refresh token for user {token.user.username}: {str(e)}'
                self.stdout.write(self.style.ERROR(error_message))
                logger.error(error_message)