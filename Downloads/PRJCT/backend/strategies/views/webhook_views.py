import json
import logging
import time
import hmac
import hashlib
import secrets
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db import models, transaction
from django.db.models.functions import ExtractHour
from django.conf import settings
from django.core.cache import cache

from ..models import Webhook, WebhookLog, ActivatedStrategy
from ..brokers.tradovate.models import TradovateAccount, TradovateToken
from .utils import (
    WebhookValidationError,
    get_client_ip,
    validate_tradingview_payload,
    validate_trendspider_payload,
    normalize_payload,
    get_sample_payload
)
from .webhook_processor import process_webhook_payload

logger = logging.getLogger(__name__)

@csrf_exempt
@login_required
def generate_webhook(request):
    """Generate a new webhook with a secure signature."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=405)
    
    try:
        data = json.loads(request.body)
        name = data.get('name')
        details = data.get('details')
        source_type = data.get('source_type', 'custom')
        
        webhook = Webhook.objects.create(
            user=request.user,
            name=name,
            details=details,
            source_type=source_type,
            secret_key=secrets.token_hex(32),
            require_signature=True
        )
        
        webhook_url = webhook.get_webhook_url_with_hmac()
        
        return JsonResponse({
            'token': str(webhook.token),
            'name': webhook.name,
            'details': webhook.details,
            'source_type': webhook.source_type,
            'created_at': webhook.created_at.isoformat(),
            'webhook_url': webhook_url  # Return the complete URL
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        logger.error(f"Error generating webhook: {str(e)}", exc_info=True)
        return JsonResponse({'error': 'Internal server error'}, status=500)

@login_required
def list_webhooks(request):
    """List all webhooks for the authenticated user."""
    try:
        logger.info(f"Fetching webhooks for user {request.user.id}")
        webhooks = Webhook.objects.filter(user=request.user)
        return JsonResponse([{
            'token': str(webhook.token),
            'name': webhook.name,
            'details': webhook.details,
            'source_type': webhook.source_type,
            'created_at': webhook.created_at.isoformat(),
            'last_triggered': webhook.last_triggered.isoformat() if webhook.last_triggered else None,
            'is_active': webhook.is_active,
            'webhook_url': webhook.get_webhook_url_with_hmac()  # Add this line
        } for webhook in webhooks], safe=False)
    except Exception as e:
        logger.error(f"Error listing webhooks: {str(e)}", exc_info=True)
        return JsonResponse({'error': 'Internal server error'}, status=500)

@csrf_exempt
def webhook_endpoint(request, token):
    """Handle incoming webhook requests."""
    start_time = time.time()
    client_ip = get_client_ip(request)
    logger.info(f"Received webhook request - Token: {token}, IP: {client_ip}")
    
    try:
        if request.method != 'POST':
            return JsonResponse({
                'error': 'Method not allowed',
                'detail': 'Only POST requests are accepted'
            }, status=405)

        try:
            webhook = Webhook.objects.select_related('user').get(
                token=token,
                is_active=True
            )
        except Webhook.DoesNotExist:
            logger.error(f"Invalid webhook token: {token}")
            return JsonResponse({
                'error': 'Invalid webhook',
                'detail': 'Webhook not found or inactive'
            }, status=404)

        # Verify IP address
        if not webhook.verify_ip(client_ip):
            logger.warning(f"IP {client_ip} not allowed for webhook {token}")
            return JsonResponse({
                'error': 'Access denied',
                'detail': 'IP address not allowed'
            }, status=403)

        # Check rate limit
        if not webhook.check_rate_limit():
            logger.warning(f"Rate limit exceeded for webhook {token}")
            return JsonResponse({
                'error': 'Rate limit exceeded',
                'detail': 'Too many requests'
            }, status=429)

        # Verify secret from URL parameters
        provided_secret = request.GET.get('secret')
        if not provided_secret or provided_secret != webhook.secret_key:
            logger.warning(f"Invalid secret for webhook {token}")
            return JsonResponse({
                'error': 'Authentication failed',
                'detail': 'Invalid secret'
            }, status=401)

        # Process payload
        try:
            payload = json.loads(request.body)
        except json.JSONDecodeError:
            webhook.log_trigger(False, request.body.decode('utf-8'), "Invalid JSON payload")
            return JsonResponse({
                'error': 'Invalid payload',
                'detail': 'Request body must be valid JSON'
            }, status=400)

        # Validate payload format based on source type
        if webhook.source_type == 'tradingview' and not validate_tradingview_payload(payload):
            error_msg = "Invalid TradingView payload format"
            webhook.log_trigger(False, request.body.decode('utf-8'), error_msg)
            return JsonResponse({
                'error': 'Invalid payload',
                'detail': error_msg
            }, status=400)
        elif webhook.source_type == 'trendspider' and not validate_trendspider_payload(payload):
            error_msg = "Invalid TrendSpider payload format"
            webhook.log_trigger(False, request.body.decode('utf-8'), error_msg)
            return JsonResponse({
                'error': 'Invalid payload',
                'detail': error_msg
            }, status=400)

        # Process webhook
        try:
            with transaction.atomic():
                normalized_payload = normalize_payload(webhook.source_type, payload)
                process_webhook_payload(webhook, normalized_payload)

                processing_time = time.time() - start_time
                
                WebhookLog.objects.create(
                    webhook=webhook,
                    success=True,
                    payload=request.body.decode('utf-8'),
                    ip_address=client_ip,
                    processing_time=processing_time
                )

                webhook.last_triggered = timezone.now()
                webhook.save(update_fields=['last_triggered'])

                return JsonResponse({
                    'status': 'success',
                    'message': 'Webhook processed successfully',
                    'timestamp': timezone.now().isoformat(),
                    'processing_time': f"{processing_time:.2f}s"
                })

        except Exception as e:
            error_msg = f"Error processing webhook: {str(e)}"
            logger.error(error_msg, exc_info=True)
            
            WebhookLog.objects.create(
                webhook=webhook,
                success=False,
                payload=request.body.decode('utf-8'),
                error_message=str(e),
                ip_address=client_ip,
                processing_time=time.time() - start_time
            )

            return JsonResponse({
                'error': 'Processing error',
                'detail': str(e)
            }, status=500)

    except Exception as e:
        logger.error(f"Unexpected error in webhook endpoint: {str(e)}", exc_info=True)
        return JsonResponse({
            'error': 'Server error',
            'detail': 'An unexpected error occurred'
        }, status=500)

@csrf_exempt
@login_required
def delete_webhook(request, token):
    """Delete a specific webhook."""
    try:
        webhook = Webhook.objects.get(token=token, user=request.user)
        webhook.delete()
        return JsonResponse({'message': 'Webhook deleted successfully'})
    except Webhook.DoesNotExist:
        return JsonResponse({'error': 'Webhook not found'}, status=404)
    except Exception as e:
        logger.error(f"Error deleting webhook: {str(e)}", exc_info=True)
        return JsonResponse({'error': 'Internal server error'}, status=500)

@login_required
def webhook_statistics(request, token):
    """Get statistics for a specific webhook."""
    try:
        webhook = Webhook.objects.get(token=token, user=request.user)
        
        # Get basic stats
        total_triggers = WebhookLog.objects.filter(webhook=webhook).count()
        successful_triggers = WebhookLog.objects.filter(webhook=webhook, success=True).count()
        failed_triggers = WebhookLog.objects.filter(webhook=webhook, success=False).count()
        
        # Get hourly distribution
        hourly_distribution = (
            WebhookLog.objects
            .filter(webhook=webhook)
            .annotate(hour=ExtractHour('triggered_at'))
            .values('hour')
            .annotate(count=models.Count('id'))
            .order_by('hour')
        )
        
        # Get recent errors
        recent_errors = (
            WebhookLog.objects
            .filter(webhook=webhook, success=False)
            .order_by('-triggered_at')
            .values('triggered_at', 'error_message')[:5]
        )
        
        return JsonResponse({
            'total_triggers': total_triggers,
            'successful_triggers': successful_triggers,
            'failed_triggers': failed_triggers,
            'hourly_distribution': list(hourly_distribution),
            'recent_errors': list(recent_errors),
            'success_rate': (successful_triggers / total_triggers * 100) if total_triggers > 0 else 0
        })
        
    except Webhook.DoesNotExist:
        return JsonResponse({'error': 'Webhook not found'}, status=404)
    except Exception as e:
        logger.error(f"Error getting webhook statistics: {str(e)}", exc_info=True)
        return JsonResponse({'error': 'Internal server error'}, status=500)

@login_required
def list_webhook_logs(request, token):
    """Get logs for a specific webhook."""
    try:
        webhook = Webhook.objects.get(token=token, user=request.user)
        
        # Get pagination parameters
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 50))
        
        # Calculate offset and limit
        offset = (page - 1) * page_size
        limit = page_size
        
        # Get logs with pagination
        logs = WebhookLog.objects.filter(webhook=webhook).order_by('-triggered_at')[offset:offset + limit]
        
        return JsonResponse([{
            'id': log.id,
            'success': log.success,
            'triggered_at': log.triggered_at.isoformat(),
            'ip_address': log.ip_address,
            'processing_time': log.processing_time,
            'error_message': log.error_message,
            'payload': log.payload
        } for log in logs], safe=False)
        
    except Webhook.DoesNotExist:
        return JsonResponse({'error': 'Webhook not found'}, status=404)
    except Exception as e:
        logger.error(f"Error listing webhook logs: {str(e)}", exc_info=True)
        return JsonResponse({'error': 'Internal server error'}, status=500)

@login_required
def clear_webhook_logs(request, token):
    """Clear all logs for a specific webhook."""
    try:
        webhook = Webhook.objects.get(token=token, user=request.user)
        WebhookLog.objects.filter(webhook=webhook).delete()
        return JsonResponse({'message': 'Webhook logs cleared successfully'})
    except Webhook.DoesNotExist:
        return JsonResponse({'error': 'Webhook not found'}, status=404)
    except Exception as e:
        logger.error(f"Error clearing webhook logs: {str(e)}", exc_info=True)
        return JsonResponse({'error': 'Internal server error'}, status=500)

@login_required
def test_webhook(request, token):
    """Test a webhook with a sample payload."""
    try:
        webhook = Webhook.objects.get(token=token, user=request.user)
        sample_payload = get_sample_payload(webhook.source_type)
        
        try:
            process_webhook_payload(webhook, sample_payload)
            return JsonResponse({
                'message': 'Test successful',
                'payload_used': sample_payload
            })
        except Exception as e:
            return JsonResponse({
                'error': 'Test failed',
                'message': str(e),
                'payload_used': sample_payload
            }, status=400)
            
    except Webhook.DoesNotExist:
        return JsonResponse({'error': 'Webhook not found'}, status=404)
    except Exception as e:
        logger.error(f"Error testing webhook: {str(e)}", exc_info=True)
        return JsonResponse({'error': 'Internal server error'}, status=500)

@login_required
def webhook_details(request, token):
    """Get detailed information about a specific webhook."""
    try:
        webhook = Webhook.objects.get(token=token, user=request.user)
        
        # Get recent statistics
        recent_logs = WebhookLog.objects.filter(
            webhook=webhook,
            triggered_at__gte=timezone.now() - timedelta(hours=24)
        )
        recent_success = recent_logs.filter(success=True).count()
        recent_total = recent_logs.count()
        
        return JsonResponse({
            'token': str(webhook.token),
            'name': webhook.name,
            'details': webhook.details,
            'source_type': webhook.source_type,
            'created_at': webhook.created_at.isoformat(),
            'last_triggered': webhook.last_triggered.isoformat() if webhook.last_triggered else None,
            'is_active': webhook.is_active,
            'webhook_auth': webhook.get_webhook_url_with_hmac(),
            'sample_payload': get_sample_payload(webhook.source_type),
            'recent_stats': {
                'success_rate': (recent_success / recent_total * 100) if recent_total > 0 else 0,
                'total_triggers': recent_total,
                'successful_triggers': recent_success
            }
        })
    except Webhook.DoesNotExist:
        return JsonResponse({'error': 'Webhook not found'}, status=404)
    except Exception as e:
        logger.error(f"Error getting webhook details: {str(e)}", exc_info=True)
        return JsonResponse({'error': 'Internal server error'}, status=500)