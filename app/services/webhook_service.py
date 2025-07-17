from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import json
import hmac
import hashlib
import logging
import os
from redis.exceptions import RedisError
from fastapi import HTTPException

from ..models.webhook import Webhook, WebhookLog
from ..models.strategy import ActivatedStrategy
from ..core.brokers.base import BaseBroker
from ..services.strategy_service import StrategyProcessor
from ..core.config import settings
from ..core.redis_manager import get_redis_connection
from ..core.correlation import CorrelationManager
from ..core.enhanced_logging import get_enhanced_logger, logging_context, operation_logging
from ..core.alert_manager import TradingAlerts
from ..core.graceful_shutdown import shutdown_manager

logger = get_enhanced_logger(__name__)

class WebhookProcessor:
    def __init__(self, db: Session):
        self.db = db
        self.strategy_processor = StrategyProcessor(db)
        self.is_railway = os.getenv("RAILWAY_ENVIRONMENT") is not None
    
    def _generate_idempotency_key(self, webhook_id: int, payload: Dict[str, Any]) -> str:
        """Generate idempotency key from webhook ID and payload content"""
        key_data = {
            "webhook_id": webhook_id,
            "action": payload.get("action"),
            "timestamp": payload.get("timestamp", ""),
            "source": payload.get("source", "")
        }
        key_string = json.dumps(key_data, sort_keys=True)
        key_hash = hashlib.sha256(key_string.encode()).hexdigest()
        return f"webhook_idempotency:{webhook_id}:{key_hash[:16]}"
    
    def _check_and_set_idempotency(self, key: str, response_data: Dict[str, Any], ttl: int = 300) -> Optional[Dict[str, Any]]:
        """Check if request is duplicate and set idempotency key. Returns existing response if duplicate."""
        with get_redis_connection() as redis_client:
            if not redis_client:
                logger.debug("Redis not available for idempotency check")
                return None
            
            try:
                # Check if key exists
                existing_response = redis_client.get(key)
                if existing_response:
                    logger.info(f"Duplicate webhook request detected, returning cached response: {key}")
                    return json.loads(existing_response)
                
                # Set the key with response data
                redis_client.setex(key, ttl, json.dumps(response_data))
                return None
                
            except RedisError as e:
                logger.warning(f"Redis error during idempotency check: {e}")
                return None
            except Exception as e:
                logger.error(f"Unexpected error during idempotency check: {e}")
                return None

    def verify_signature(self, payload: str, signature: str, secret: str) -> bool:
        """Verify webhook signature"""
        computed_signature = hmac.new(
            secret.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(computed_signature, signature)

    def normalize_payload(self, source_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize webhook payload to standard format"""
        try:
            # Handle Enum string representation
            if 'action' in payload:
                action_str = str(payload['action']).strip()
                if '.' in action_str and 'WEBHOOKACTION' in action_str:
                    action_str = action_str.split('.')[-1]
                payload['action'] = action_str.upper()

            # Rest of validation logic
            if 'action' not in payload:
                raise ValueError("Missing required field: action")

            action = payload['action']
            if action not in {'BUY', 'SELL'}:
                raise ValueError(f"Invalid action: {action}. Must be BUY or SELL.")

            # Create normalized payload
            normalized = {
                'action': action,
                'timestamp': datetime.utcnow().isoformat(),
                'source': source_type,
            }

            return normalized

        except ValueError as ve:
            raise HTTPException(
                status_code=400,
                detail=str(ve)
            )
        except Exception as e:
            logger.error(f"Payload normalization failed: {str(e)}")
            raise HTTPException(
                status_code=400,
                detail=f"Invalid payload format: {str(e)}"
            )

    async def process_webhook(
        self,
        webhook: Webhook,
        payload: Dict[str, Any],
        client_ip: str
    ) -> Dict[str, Any]:
        """Process incoming webhook data"""
        start_time = datetime.utcnow()
        
        # Set correlation ID for request tracking
        correlation_id = CorrelationManager.set_correlation_id()
        
        with logging_context(webhook_id=webhook.id, client_ip=client_ip, correlation_id=correlation_id):
            async with shutdown_manager.track_task(
                "webhook_processing", 
                f"webhook_{webhook.id}",
                webhook_id=webhook.id,
                client_ip=client_ip
            ):
                return await self._process_webhook_internal(webhook, payload, client_ip, start_time)
    
    async def _process_webhook_internal(
        self,
        webhook: Webhook,
        payload: Dict[str, Any],
        client_ip: str,
        start_time: datetime
    ) -> Dict[str, Any]:
        """Internal webhook processing with enhanced error handling"""
        
        # Check for duplicate request using idempotency protection
        idempotency_key = self._generate_idempotency_key(webhook.id, payload)
        
        # Create response structure for caching
        processing_response = {
            "status": "accepted",
            "message": "Webhook received and being processed",
            "webhook_id": webhook.id,
            "timestamp": start_time.isoformat()
        }
        
        # Check if this is a duplicate request
        cached_response = self._check_and_set_idempotency(idempotency_key, processing_response, ttl=300)
        if cached_response:
            logger.info(f"Returning cached response for duplicate webhook request: {idempotency_key}")
            return cached_response
        
        try:
            with operation_logging(logger, "webhook_processing", webhook_id=webhook.id):
                # Normalize payload based on source
                normalized_payload = self.normalize_payload(webhook.source_type, payload)
                
                # Find associated strategies
                strategies = self.db.query(ActivatedStrategy).filter(
                    ActivatedStrategy.webhook_id == webhook.token,
                    ActivatedStrategy.is_active == True
                ).all()

                if not strategies:
                    logger.warning(f"No active strategies found for webhook {webhook.token}", 
                                 extra_context={"webhook_token": webhook.token})
                    return {
                        "status": "warning",
                        "message": "No active strategies found for this webhook"
                    }

                logger.info(f"Found {len(strategies)} active strategies for webhook processing",
                           extra_context={"strategy_count": len(strategies), "webhook_token": webhook.token})

                # Execute strategies
                results = []
                strategy_errors = []
                
                for strategy in strategies:
                    try:
                        # Create order data using strategy settings
                        signal_data = {
                            "action": normalized_payload["action"],
                            "symbol": strategy.ticker,
                            "quantity": strategy.quantity if strategy.strategy_type == 'single' else strategy.leader_quantity,
                            "order_type": "MARKET",
                            "time_in_force": "GTC",
                        }

                        # Use direct execution for Railway, standard for others
                        if self.is_railway:
                            strategy_result = await self._execute_strategy_direct(strategy, signal_data)
                        else:
                            with logging_context(strategy_id=strategy.id, strategy_type=strategy.strategy_type):
                                logger.info(f"Executing strategy {strategy.id} with signal", 
                                           operation="strategy_execution",
                                           extra_context={"signal_data": signal_data})
                                
                                strategy_result = await self.strategy_processor.execute_strategy(
                                    strategy=strategy,
                                    signal_data=signal_data
                                )
                                
                                logger.info(f"Strategy {strategy.id} execution completed successfully", 
                                           operation="strategy_execution",
                                           extra_context={"result_status": strategy_result.get("status")})
                        
                        results.append({
                            "strategy_id": strategy.id,
                            "result": strategy_result
                        })
                        
                    except Exception as e:
                        error_msg = f"Strategy {strategy.id} execution failed: {str(e)}"
                        logger.exception(error_msg, operation="strategy_execution", error=e,
                                       extra_context={"strategy_id": strategy.id})
                        
                        # Send strategy failure alert
                        await TradingAlerts.strategy_failure(
                            strategy_id=str(strategy.id),
                            error=str(e),
                            context={"webhook_id": webhook.id, "action": normalized_payload["action"]}
                        )
                        
                        strategy_errors.append(error_msg)
                        results.append({
                            "strategy_id": strategy.id,
                            "error": str(e)
                        })

                # Log success with metrics
                processing_time = (datetime.utcnow() - start_time).total_seconds()
                
                logger.log_performance_metric(
                    "webhook_processing_time", 
                    processing_time, 
                    "seconds",
                    webhook_id=webhook.id,
                    strategy_count=len(strategies),
                    success_count=len([r for r in results if "error" not in r]),
                    error_count=len(strategy_errors)
                )
                
                self.log_webhook_trigger(
                    webhook=webhook,
                    success=True,
                    payload=payload,
                    error_message=None,
                    client_ip=client_ip,
                    processing_time=processing_time
                )

                return {
                    "status": "success",
                    "message": "Webhook processed successfully",
                    "results": results,
                    "processing_time": processing_time,
                    "strategy_errors": strategy_errors if strategy_errors else None
                }

        except Exception as e:
            processing_time = (datetime.utcnow() - start_time).total_seconds()
            
            logger.exception(f"Webhook processing failed", operation="webhook_processing", error=e,
                           extra_context={
                               "webhook_id": webhook.id,
                               "processing_time": processing_time,
                               "payload_action": payload.get("action")
                           })
            
            # Send webhook failure alert
            await TradingAlerts.webhook_failure(
                webhook_id=str(webhook.id),
                error=str(e),
                context={"client_ip": client_ip, "processing_time": processing_time}
            )
            
            # Log failure
            self.log_webhook_trigger(
                webhook=webhook,
                success=False,
                payload=payload,
                error_message=str(e),
                client_ip=client_ip,
                processing_time=processing_time
            )
            
            raise HTTPException(
                status_code=500,
                detail=f"Webhook processing failed: {str(e)}"
            )

    def log_webhook_trigger(
        self,
        webhook: Webhook,
        success: bool,
        payload: Dict[str, Any],
        error_message: Optional[str],
        client_ip: str,
        processing_time: float
    ) -> None:
        """Log webhook trigger attempt"""
        try:
            log = WebhookLog(
                webhook_id=webhook.id,
                success=success,
                payload=json.dumps(payload),
                error_message=error_message,
                ip_address=client_ip,
                processing_time=processing_time
            )
            
            self.db.add(log)
            webhook.last_triggered = datetime.utcnow()
            self.db.commit()

        except Exception as e:
            logger.error(f"Failed to log webhook trigger: {str(e)}", exc_info=True)
            self.db.rollback()
            # Don't raise here - logging failure shouldn't fail the webhook processing

    def _generate_rate_limit_key(self, webhook_id: int, client_ip: str) -> str:
        """Generate rate limit key for Redis"""
        return f"webhook_rate_limit:{webhook_id}:{client_ip}"
    
    def check_rate_limit_pipeline(self, webhook: Webhook, client_ip: str) -> bool:
        """Optimized rate limit check using Redis pipeline for maximum performance"""
        with get_redis_connection() as redis_client:
            if not redis_client:
                logger.debug("Redis not available, falling back to database rate limiting")
                return self._validate_rate_limit_db(webhook, client_ip)
            
            try:
                rate_limit_key = self._generate_rate_limit_key(webhook.id, client_ip)
                current_time = datetime.utcnow()
                window_start = current_time.timestamp()
                
                # Use sliding window with 1-second precision
                # Allow 10 requests per 1-second window to support HFT
                window_size = 1  # 1 second window
                max_requests = 10  # 10 requests per second for HFT support
                
                # Use pipeline to batch all Redis operations
                pipe = redis_client.pipeline()
                pipe.zremrangebyscore(rate_limit_key, 0, window_start - window_size)  # Clean old entries
                pipe.zcard(rate_limit_key)  # Count current requests
                pipe.zadd(rate_limit_key, {f"{window_start}:{client_ip}": window_start})  # Add current request
                pipe.expire(rate_limit_key, window_size + 10)  # Set expiration
                
                # Execute all operations in single round-trip
                results = pipe.execute()
                current_count = results[1]  # Get count from zcard operation
                
                if current_count >= max_requests:
                    logger.warning(f"Rate limit exceeded for webhook {webhook.id} from IP {client_ip}: {current_count} requests in {window_size}s window")
                    return False
                
                return True
                
            except RedisError as e:
                logger.warning(f"Redis pipeline error during rate limit check: {e}, falling back to database")
                return self._validate_rate_limit_db(webhook, client_ip)
            except Exception as e:
                logger.error(f"Unexpected error during rate limit check: {e}, falling back to database")
                return self._validate_rate_limit_db(webhook, client_ip)
    
    def check_rate_limit(self, webhook: Webhook, client_ip: str) -> bool:
        """Check if request exceeds rate limit using Redis sliding window with Railway optimization"""
        # Use pipeline optimization for Railway
        if self.is_railway:
            return self.check_rate_limit_pipeline(webhook, client_ip)
        with get_redis_connection() as redis_client:
            if not redis_client:
                logger.debug("Redis not available, falling back to database rate limiting")
                return self._validate_rate_limit_db(webhook, client_ip)
            
            try:
                rate_limit_key = self._generate_rate_limit_key(webhook.id, client_ip)
                current_time = datetime.utcnow()
                window_start = current_time.timestamp()
                
                # Use sliding window with 1-second precision
                # Allow 10 requests per 1-second window to support HFT
                window_size = 1  # 1 second window
                max_requests = 10  # 10 requests per second for HFT support
                
                # Remove old entries outside the window
                redis_client.zremrangebyscore(
                    rate_limit_key, 
                    0, 
                    window_start - window_size
                )
                
                # Count current requests in window
                current_count = redis_client.zcard(rate_limit_key)
                
                if current_count >= max_requests:
                    logger.warning(f"Rate limit exceeded for webhook {webhook.id} from IP {client_ip}: {current_count} requests in {window_size}s window")
                    return False
                
                # Add current request to window
                request_id = f"{window_start}:{client_ip}"
                redis_client.zadd(rate_limit_key, {request_id: window_start})
                
                # Set expiration for cleanup (window_size + buffer)
                redis_client.expire(rate_limit_key, window_size + 10)
                
                return True
                
            except RedisError as e:
                logger.warning(f"Redis error during rate limit check: {e}, falling back to database")
                return self._validate_rate_limit_db(webhook, client_ip)
            except Exception as e:
                logger.error(f"Unexpected error during rate limit check: {e}, falling back to database")
                return self._validate_rate_limit_db(webhook, client_ip)
    
    def _validate_rate_limit_db(self, webhook: Webhook, client_ip: str) -> bool:
        """Fallback rate limit validation using database"""
        try:
            from datetime import timedelta
            current_time = datetime.utcnow()
            one_second_ago = current_time - timedelta(seconds=1)
            
            # Count triggers in last second for this specific webhook and IP
            recent_triggers = self.db.query(WebhookLog).filter(
                WebhookLog.webhook_id == webhook.id,
                WebhookLog.ip_address == client_ip,
                WebhookLog.triggered_at >= one_second_ago
            ).count()
            
            # Allow 10 requests per second for HFT support
            return recent_triggers < 10
            
        except Exception as e:
            logger.error(f"Database rate limit validation failed: {str(e)}", exc_info=True)
            # On error, allow the request (fail open for availability)
            return True

    async def _execute_strategy_direct(self, strategy, signal_data: Dict[str, Any]) -> Dict[str, Any]:
        """Direct strategy execution for Railway optimization"""
        try:
            from app.models.broker import BrokerAccount
            from app.core.brokers.base import BaseBroker
            from app.utils.ticker_utils import validate_ticker
            
            # Get account
            account = self.db.query(BrokerAccount).filter(
                BrokerAccount.account_id == strategy.account_id,
                BrokerAccount.is_active == True
            ).first()

            if not account:
                return {"status": "error", "error": "Trading account not found"}

            if not account.credentials or not account.credentials.is_valid:
                return {"status": "error", "error": "Invalid account credentials"}

            # Get broker and validate ticker
            broker = BaseBroker.get_broker_instance(account.broker_id, self.db)
            valid, contract_ticker = validate_ticker(strategy.ticker)
            if not valid:
                return {"status": "error", "error": f"Invalid ticker: {strategy.ticker}"}

            # Execute order
            order_data = {
                "account_id": account.account_id,
                "symbol": contract_ticker,
                "quantity": strategy.quantity,
                "side": signal_data["action"],
                "type": signal_data.get("order_type", "MARKET"),
                "time_in_force": signal_data.get("time_in_force", "GTC"),
            }

            order_result = await broker.place_order(account, order_data)
            return {"status": "success", "order_details": order_result}
                    
        except Exception as e:
            return {"status": "error", "error": str(e)}


