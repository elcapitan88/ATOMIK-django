# Generated by Django 5.1.1 on 2024-12-17 01:46

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('strategies', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TradovateAccount',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('account_id', models.CharField(max_length=100)),
                ('name', models.CharField(default='Tradovate Account', max_length=200)),
                ('nickname', models.CharField(blank=True, max_length=100, null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('environment', models.CharField(choices=[('live', 'Live'), ('demo', 'Demo')], default='demo', max_length=10)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('last_connected', models.DateTimeField(blank=True, null=True)),
                ('status', models.CharField(choices=[('active', 'Active'), ('inactive', 'Inactive'), ('connecting', 'Connecting'), ('error', 'Error')], default='inactive', max_length=20)),
                ('error_message', models.TextField(blank=True, null=True)),
                ('balance', models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True)),
                ('margin_used', models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True)),
                ('available_margin', models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True)),
                ('day_pnl', models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True)),
                ('broker', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tradovate_accounts', to='strategies.broker')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tradovate_accounts', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
                'unique_together': {('broker', 'account_id')},
            },
        ),
        migrations.CreateModel(
            name='TradovateOrder',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tradovate_order_id', models.CharField(max_length=100)),
                ('webhook_id', models.UUIDField()),
                ('order_type', models.CharField(max_length=20)),
                ('action', models.CharField(max_length=10)),
                ('symbol', models.CharField(max_length=20)),
                ('quantity', models.IntegerField()),
                ('price', models.DecimalField(blank=True, decimal_places=4, max_digits=15, null=True)),
                ('status', models.CharField(max_length=20)),
                ('raw_request', models.JSONField()),
                ('raw_response', models.JSONField()),
                ('error_message', models.TextField(blank=True, null=True)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='orders', to='strategies_tradovate.tradovateaccount')),
                ('strategy', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tradovate_orders', to='strategies.activatedstrategy')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='TradovateToken',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('access_token', models.TextField()),
                ('refresh_token', models.TextField()),
                ('md_access_token', models.TextField(blank=True, null=True)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('last_refreshed', models.DateTimeField(blank=True, null=True)),
                ('expires_in', models.IntegerField(default=4800)),
                ('environment', models.CharField(choices=[('live', 'Live'), ('demo', 'Demo')], default='demo', max_length=10)),
                ('is_valid', models.BooleanField(default=True)),
                ('error_count', models.IntegerField(default=0)),
                ('last_error', models.TextField(blank=True, null=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tradovate_tokens', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
                'unique_together': {('user', 'environment')},
            },
        ),
    ]