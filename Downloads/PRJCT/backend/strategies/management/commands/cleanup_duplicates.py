# strategies/management/commands/cleanup_duplicates.py
from django.core.management.base import BaseCommand
from django.db.models import Count
from strategies.models import ActivatedStrategy
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Cleanup duplicate strategies'

    def handle(self, *args, **options):
        # Clean up single account strategies
        duplicates = (
            ActivatedStrategy.objects
            .filter(strategy_type='single')
            .values('user_id', 'webhook_id', 'account_id')
            .annotate(count=Count('id'))
            .filter(count__gt=1)
        )

        for dup in duplicates:
            strategies = ActivatedStrategy.objects.filter(
                user_id=dup['user_id'],
                webhook_id=dup['webhook_id'],
                account_id=dup['account_id'],
                strategy_type='single'
            ).order_by('created_at')
            
            first = strategies.first()
            to_delete = strategies.exclude(id=first.id)
            count = to_delete.count()
            to_delete.delete()
            self.stdout.write(f"Deleted {count} duplicate single account strategies for {dup}")

        # Clean up multiple account strategies
        duplicates = (
            ActivatedStrategy.objects
            .filter(strategy_type='multiple')
            .values('user_id', 'webhook_id', 'leader_account_id')
            .annotate(count=Count('id'))
            .filter(count__gt=1)
        )

        for dup in duplicates:
            strategies = ActivatedStrategy.objects.filter(
                user_id=dup['user_id'],
                webhook_id=dup['webhook_id'],
                leader_account_id=dup['leader_account_id'],
                strategy_type='multiple'
            ).order_by('created_at')
            
            first = strategies.first()
            to_delete = strategies.exclude(id=first.id)
            count = to_delete.count()
            to_delete.delete()
            self.stdout.write(f"Deleted {count} duplicate multiple account strategies for {dup}")

        self.stdout.write(self.style.SUCCESS('Successfully cleaned up duplicate strategies'))