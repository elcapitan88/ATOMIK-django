from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session
import json
import hmac
import hashlib
import logging
from fastapi import HTTPException

from ..models.webhook import Webhook, WebhookLog
from ..models.strategy import ActivatedStrategy
from ..core.brokers.base import BaseBroker
from ..services.strategy_service import StrategyProcessor

logger = logging.getLogger(__name__)

class WebhookProcessor:
    def __init__(self, db: Session):
        self.db = db
        self.strategy_processor = StrategyProcessor(db)

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
        
        try:
            # Normalize payload based on source
            normalized_payload = self.normalize_payload(webhook.source_type, payload)
            
            # Find associated strategies
            strategies = self.db.query(ActivatedStrategy).filter(
                ActivatedStrategy.webhook_id == webhook.token,
                ActivatedStrategy.is_active == True
            ).all()

            if not strategies:
                logger.warning(f"No active strategies found for webhook {webhook.token}")
                return {
                    "status": "warning",
                    "message": "No active strategies found for this webhook"
                }

            # Execute strategies
            results = []
            for strategy in strategies:
                try:
                    # Create order data using strategy settings
                    signal_data = {
                        "action": normalized_payload["action"],
                        "symbol": strategy.ticker,
                        "quantity": strategy.quantity if strategy.strategy_type == 'single' else strategy.leader_quantity,
                        "order_type": "MARKET",  # Default to market orders for now
                        "time_in_force": "GTC",  # Good Till Cancelled
                    }

                    logger.info(f"Executing strategy {strategy.id} with signal: {signal_data}")
                    
                    strategy_result = await self.strategy_processor.execute_strategy(
                        strategy=strategy,
                        signal_data=signal_data
                    )
                    
                    results.append({
                        "strategy_id": strategy.id,
                        "result": strategy_result
                    })
                    
                    logger.info(f"Strategy {strategy.id} execution completed: {strategy_result}")
                    
                except Exception as e:
                    logger.error(f"Strategy execution failed: {str(e)}", exc_info=True)
                    results.append({
                        "strategy_id": strategy.id,
                        "error": str(e)
                    })

            # Log success
            processing_time = (datetime.utcnow() - start_time).total_seconds()
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
                "processing_time": processing_time
            }

        except Exception as e:
            logger.error(f"Webhook processing failed: {str(e)}", exc_info=True)
            # Log failure
            processing_time = (datetime.utcnow() - start_time).total_seconds()
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

    def validate_rate_limit(self, webhook: Webhook, client_ip: str) -> bool:
        """Validate webhook against rate limits"""
        try:
            current_time = datetime.utcnow()
            one_minute_ago = current_time - timedelta(minutes=1)
            
            # Count triggers in last minute
            recent_triggers = self.db.query(WebhookLog).filter(
                WebhookLog.webhook_id == webhook.id,
                WebhookLog.ip_address == client_ip,
                WebhookLog.triggered_at >= one_minute_ago
            ).count()
            
            return recent_triggers < webhook.max_triggers_per_minute
            
        except Exception as e:
            logger.error(f"Rate limit validation failed: {str(e)}", exc_info=True)
            return False