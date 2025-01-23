from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from datetime import datetime
import logging
import hmac
import hashlib
import json
from fastapi import HTTPException, Request
import asyncio

from .event_handlers import Event, EventType, EventPriority

logger = logging.getLogger(__name__)

class WebhookValidationError(Exception):
    """Exception raised for webhook validation errors."""
    pass

class BaseWebhookHandler(ABC):
    """Abstract base class for webhook handlers."""
    
    def __init__(self, secret_key: str):
        self.secret_key = secret_key
        self._event_callbacks: List[callable] = []
        self._processing_lock = asyncio.Lock()
        
    @abstractmethod
    async def validate_signature(self, payload: bytes, signature: str) -> bool:
        """Validate webhook signature."""
        pass
        
    @abstractmethod
    async def process_webhook(self, payload: Dict[str, Any]) -> Event:
        """Process webhook payload and convert to internal event."""
        pass
    
    def register_event_callback(self, callback: callable):
        """Register callback for processed events."""
        self._event_callbacks.append(callback)
        
    async def _notify_event_callbacks(self, event: Event):
        """Notify all registered callbacks of new event."""
        for callback in self._event_callbacks:
            try:
                await callback(event)
            except Exception as e:
                logger.error(f"Error in event callback: {str(e)}")

    async def handle_webhook(self, request: Request) -> Dict[str, Any]:
        """Main webhook handling method."""
        try:
            # Get payload and signature
            payload_bytes = await request.body()
            signature = request.headers.get('X-Webhook-Signature')
            
            if not signature:
                raise WebhookValidationError("Missing webhook signature")
                
            # Validate signature
            if not await self.validate_signature(payload_bytes, signature):
                raise WebhookValidationError("Invalid webhook signature")
                
            # Parse payload
            payload = json.loads(payload_bytes)
            
            # Process webhook with lock to prevent race conditions
            async with self._processing_lock:
                event = await self.process_webhook(payload)
                
            # Notify callbacks
            await self._notify_event_callbacks(event)
            
            return {"status": "success", "message": "Webhook processed successfully"}
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON payload: {str(e)}")
            raise HTTPException(status_code=400, detail="Invalid JSON payload")
            
        except WebhookValidationError as e:
            logger.error(f"Webhook validation error: {str(e)}")
            raise HTTPException(status_code=401, detail=str(e))
            
        except Exception as e:
            logger.error(f"Error processing webhook: {str(e)}")
            raise HTTPException(status_code=500, detail="Internal server error")

class TradovateWebhookHandler(BaseWebhookHandler):
    """Tradovate-specific webhook handler implementation."""
    
    async def validate_signature(self, payload: bytes, signature: str) -> bool:
        """Validate Tradovate webhook signature."""
        try:
            # Compute HMAC using secret key
            computed_hash = hmac.new(
                self.secret_key.encode(),
                payload,
                hashlib.sha256
            ).hexdigest()
            
            # Compare with provided signature
            return hmac.compare_digest(computed_hash, signature)
            
        except Exception as e:
            logger.error(f"Error validating signature: {str(e)}")
            return False
            
    async def process_webhook(self, payload: Dict[str, Any]) -> Event:
        """Process Tradovate webhook payload."""
        try:
            # Extract event type from payload
            event_type = self._determine_event_type(payload)
            
            # Transform payload based on event type
            transformed_data = await self._transform_payload(payload, event_type)
            
            # Create event
            event = Event(
                event_type=event_type,
                data=transformed_data,
                timestamp=datetime.utcnow(),
                priority=self._determine_priority(event_type),
                source="tradovate_webhook"
            )
            
            logger.info(f"Processed Tradovate webhook: {event_type.value}")
            return event
            
        except Exception as e:
            logger.error(f"Error processing Tradovate webhook: {str(e)}")
            raise
            
    def _determine_event_type(self, payload: Dict[str, Any]) -> EventType:
        """Determine event type from Tradovate payload."""
        event_mapping = {
            "MD": EventType.MARKET_DATA,
            "ORDER": EventType.ORDER_UPDATE,
            "POSITION": EventType.POSITION_UPDATE,
            "ACCOUNT": EventType.ACCOUNT_UPDATE,
            "TRADE": EventType.TRADE_UPDATE,
        }
        
        payload_type = payload.get("type", "").upper()
        return event_mapping.get(payload_type, EventType.ERROR)
        
    def _determine_priority(self, event_type: EventType) -> EventPriority:
        """Determine priority based on event type."""
        priority_mapping = {
            EventType.MARKET_DATA: EventPriority.HIGH,
            EventType.ORDER_UPDATE: EventPriority.HIGH,
            EventType.POSITION_UPDATE: EventPriority.MEDIUM,
            EventType.ACCOUNT_UPDATE: EventPriority.MEDIUM,
            EventType.TRADE_UPDATE: EventPriority.HIGH,
            EventType.ERROR: EventPriority.HIGH,
        }
        
        return priority_mapping.get(event_type, EventPriority.MEDIUM)
        
    async def _transform_payload(
        self,
        payload: Dict[str, Any],
        event_type: EventType
    ) -> Dict[str, Any]:
        """Transform Tradovate payload into standardized format."""
        if event_type == EventType.MARKET_DATA:
            return {
                "symbol": payload.get("contractId"),
                "price": payload.get("lastPrice"),
                "volume": payload.get("volume"),
                "timestamp": payload.get("timestamp"),
                "bid": payload.get("bidPrice"),
                "ask": payload.get("askPrice"),
                "raw_payload": payload  # Store original payload for reference
            }
            
        elif event_type == EventType.ORDER_UPDATE:
            return {
                "order_id": payload.get("orderId"),
                "status": payload.get("orderStatus"),
                "symbol": payload.get("contractId"),
                "quantity": payload.get("qty"),
                "filled_quantity": payload.get("filledQty"),
                "price": payload.get("price"),
                "timestamp": payload.get("timestamp"),
                "raw_payload": payload
            }
            
        elif event_type == EventType.POSITION_UPDATE:
            return {
                "account_id": payload.get("accountId"),
                "symbol": payload.get("contractId"),
                "position": payload.get("netPosition"),
                "avg_entry_price": payload.get("avgPrice"),
                "unrealized_pl": payload.get("unrealizedPL"),
                "realized_pl": payload.get("realizedPL"),
                "timestamp": payload.get("timestamp"),
                "raw_payload": payload
            }
            
        elif event_type == EventType.ACCOUNT_UPDATE:
            return {
                "account_id": payload.get("accountId"),
                "balance": payload.get("balance"),
                "margin_used": payload.get("marginUsed"),
                "margin_available": payload.get("marginAvailable"),
                "timestamp": payload.get("timestamp"),
                "raw_payload": payload
            }
            
        else:
            return {
                "error": "Unsupported event type",
                "raw_payload": payload
            }