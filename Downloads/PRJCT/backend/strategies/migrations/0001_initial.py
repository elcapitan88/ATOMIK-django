# Generated by Django 5.1.1 on 2024-12-17 01:44

import django.db.models.deletion
import django.utils.timezone
import secrets
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Broker',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('slug', models.SlugField(unique=True)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='BrokerAccount',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('account_id', models.CharField(max_length=100)),
                ('nickname', models.CharField(blank=True, max_length=100, null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('environment', models.CharField(choices=[('live', 'Live'), ('demo', 'Demo')], default='demo', max_length=10)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('broker', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='strategies.broker')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
                'unique_together': {('broker', 'account_id')},
            },
        ),
        migrations.CreateModel(
            name='Webhook',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('secret_key', models.CharField(default=secrets.token_hex, help_text='Secret key for signing webhook payloads', max_length=64)),
                ('name', models.CharField(blank=True, max_length=255, null=True)),
                ('details', models.TextField(blank=True, null=True)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('last_triggered', models.DateTimeField(blank=True, null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('source_type', models.CharField(choices=[('tradingview', 'TradingView'), ('trendspider', 'TrendSpider'), ('custom', 'Custom')], default='custom', max_length=50)),
                ('allowed_ips', models.TextField(blank=True, help_text='Comma-separated list of allowed IP addresses', null=True)),
                ('max_triggers_per_minute', models.IntegerField(default=60)),
                ('require_signature', models.BooleanField(default=True)),
                ('max_retries', models.IntegerField(default=3)),
                ('retry_interval', models.IntegerField(default=60)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='webhooks', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='WebhookLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('triggered_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('success', models.BooleanField(default=True)),
                ('payload', models.TextField()),
                ('error_message', models.TextField(blank=True, null=True)),
                ('ip_address', models.GenericIPAddressField(null=True)),
                ('processing_time', models.FloatField(help_text='Processing time in seconds', null=True)),
                ('webhook', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='logs', to='strategies.webhook')),
            ],
            options={
                'ordering': ['-triggered_at'],
            },
        ),
        migrations.CreateModel(
            name='ActivatedStrategy',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('strategy_type', models.CharField(choices=[('single', 'Single Account'), ('multiple', 'Multiple Account')], default='single', max_length=20)),
                ('webhook_id', models.UUIDField()),
                ('account_id', models.CharField(blank=True, help_text='Account ID for single account strategy', max_length=100, null=True)),
                ('leader_account_id', models.CharField(blank=True, help_text='Leader account ID for group strategy', max_length=100, null=True)),
                ('quantity', models.IntegerField(blank=True, help_text='Trade quantity for single account', null=True)),
                ('leader_quantity', models.IntegerField(blank=True, help_text='Trade quantity for leader account', null=True)),
                ('follower_quantity', models.IntegerField(blank=True, help_text='Trade quantity for follower accounts', null=True)),
                ('ticker', models.CharField(help_text='Trading symbol', max_length=10)),
                ('group_name', models.CharField(blank=True, help_text='Name for group strategy', max_length=100, null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('last_triggered', models.DateTimeField(blank=True, null=True)),
                ('total_trades', models.IntegerField(default=0)),
                ('successful_trades', models.IntegerField(default=0)),
                ('failed_trades', models.IntegerField(default=0)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='strategies', to=settings.AUTH_USER_MODEL)),
                ('follower_accounts', models.ManyToManyField(blank=True, related_name='following_strategies', to='strategies.brokeraccount')),
            ],
            options={
                'verbose_name': 'Activated Strategy',
                'verbose_name_plural': 'Activated Strategies',
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['user', 'is_active'], name='strategies__user_id_a770f8_idx'), models.Index(fields=['webhook_id'], name='strategies__webhook_323a68_idx')],
            },
        ),
        migrations.AddIndex(
            model_name='webhook',
            index=models.Index(fields=['user', 'is_active'], name='strategies__user_id_848d55_idx'),
        ),
        migrations.AddIndex(
            model_name='webhook',
            index=models.Index(fields=['token'], name='strategies__token_f2c9f4_idx'),
        ),
        migrations.AddIndex(
            model_name='webhooklog',
            index=models.Index(fields=['webhook', 'triggered_at'], name='strategies__webhook_7e4369_idx'),
        ),
        migrations.AddIndex(
            model_name='webhooklog',
            index=models.Index(fields=['success'], name='strategies__success_a8fb4d_idx'),
        ),
    ]
