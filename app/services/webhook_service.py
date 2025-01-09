from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session
import json
import hmac
import hashlib
import logging

from ..models.webhook import Webhook, WebhookLog
from ..models.strategy import ActivatedStrategy
from ..core.brokers.base import BaseBroker
from ..services.strategy_service import StrategyProcessor
from fastapi import HTTPException

logger = logging.getLogger(__name__)

class WebhookProcessor:
    def __init__(self, db: Session):
        self.db = db
        self.strategy_processor = StrategyProcessor(db)

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
                    strategy_result = await self.strategy_processor.execute_strategy(
                        strategy=strategy,
                        signal_data=normalized_payload
                    )
                    results.append({
                        "strategy_id": strategy.id,
                        "result": strategy_result
                    })
                except Exception as e:
                    logger.error(f"Strategy execution failed: {str(e)}")
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
            logger.error(f"Webhook processing failed: {str(e)}")
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

    def normalize_payload(
        self,
        source_type: str,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Normalize webhook payload to standard format"""
        try:
            # Validate required fields
            required_fields = {'action', 'symbol'}
            if not all(field in payload for field in required_fields):
                missing = required_fields - set(payload.keys())
                raise ValueError(f"Missing required fields: {missing}")

            # Normalize action
            action = payload['action'].upper()
            if action not in {'BUY', 'SELL'}:
                raise ValueError(f"Invalid action: {action}. Must be BUY or SELL.")

            # Create normalized payload
            normalized = {
                'action': action,
                'symbol': payload['symbol'].upper(),
                'order_type': payload.get('type', 'MARKET').upper(),
                'price': float(payload['price']) if 'price' in payload else None,
                'quantity': float(payload['quantity']) if 'quantity' in payload else None,
                'stop_price': float(payload['stop_price']) if 'stop_price' in payload else None,
                'time_in_force': payload.get('time_in_force', 'GTC').upper(),
                'timestamp': datetime.utcnow().isoformat(),
                'source': source_type,
                # Preserve any additional metadata
                'metadata': {
                    k: v for k, v in payload.items()
                    if k not in {'action', 'symbol', 'type', 'price', 'quantity', 
                               'stop_price', 'time_in_force'}
                }
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

    def verify_signature(self, payload: str, signature: str, secret: str) -> bool:
        """Verify webhook signature"""
        computed_signature = hmac.new(
            secret.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(computed_signature, signature)

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
            logger.error(f"Failed to log webhook trigger: {str(e)}")
            # Don't raise here - logging failure shouldn't fail the webhook processing