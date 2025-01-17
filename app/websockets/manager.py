import asyncio
import logging
import json
import uuid
import redis
from datetime import datetime, timedelta
from typing import Dict, Set, Optional, Any
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from app.db.base import SessionLocal  

from ..models.websocket import (
    WebSocketConnection,
    ConnectionStatus,
    MessageCategory
)
from ..models.user import User
from ..models.subscription import SubscriptionStatus, SubscriptionTier
from ..core.config import settings

logger = logging.getLogger(__name__)

class ConnectionStats:
    """Track connection statistics"""
    def __init__(self):
        self.connected_at: datetime = datetime.utcnow()
        self.last_heartbeat: datetime = datetime.utcnow()
        self.messages_received: int = 0
        self.messages_sent: int = 0
        self.errors: int = 0
        self.reconnections: int = 0
        self.subscribed_symbols: Set[str] = set()

    def update_heartbeat(self):
        """Update last heartbeat time"""
        self.last_heartbeat = datetime.utcnow()

    def increment_errors(self):
        """Increment error count"""
        self.errors += 1

    def increment_reconnections(self):
        """Increment reconnection count"""
        self.reconnections += 1

class ClientMetadata:
    """Store client connection metadata"""
    def __init__(
        self,
        user_id: int,
        client_id: str,
        environment: str,
        broker: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ):
        self.user_id = user_id
        self.client_id = client_id
        self.environment = environment
        self.broker = broker
        self.ip_address = ip_address
        self.user_agent = user_agent
        self.created_at = datetime.utcnow()

    def to_dict(self) -> dict:
        """Convert metadata to dictionary"""
        return {
            "user_id": self.user_id,
            "client_id": self.client_id,
            "environment": self.environment,
            "broker": self.broker,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "created_at": self.created_at.isoformat()
        }

class ConnectionInfo:
    """Store complete connection information"""
    def __init__(
        self,
        websocket: WebSocket,
        client_id: str,
        user_id: int,
        metadata: ClientMetadata,
        stats: ConnectionStats
    ):
        self.websocket = websocket
        self.client_id = client_id
        self.user_id = user_id
        self.metadata = metadata
        self.stats = stats
        self.status = ConnectionStatus.CONNECTED

    async def close(self):
        """Close the websocket connection"""
        try:
            await self.websocket.close()
        except Exception as e:
            logger.error(f"Error closing websocket: {str(e)}")

    def get_connection_info(self) -> dict:
        """Get complete connection information"""
        return {
            "client_id": self.client_id,
            "user_id": self.user_id,
            "status": self.status,
            "metadata": self.metadata.to_dict(),
            "stats": {
                "connected_at": self.stats.connected_at.isoformat(),
                "last_heartbeat": self.stats.last_heartbeat.isoformat(),
                "messages_received": self.stats.messages_received,
                "messages_sent": self.stats.messages_sent,
                "errors": self.stats.errors,
                "reconnections": self.stats.reconnections,
                "subscribed_symbols": list(self.stats.subscribed_symbols)
            }
        }

class ManagerConfig:
    """Configuration for WebSocket manager"""
    def __init__(self):
        self.heartbeat_interval: int = 30
        self.connection_timeout: int = 60
        self.max_connections_per_user: int = 5
        self.max_subscriptions_per_client: int = 50
        self.cleanup_interval: int = 300
        self.max_message_size: int = 1024 * 1024  # 1MB
        self.enable_message_logging: bool = True
        self.broker_configs: Dict[str, Dict[str, Any]] = {}
        
        # Subscription tier limits
        self.tier_limits = {
            SubscriptionTier.STARTED: {
                "max_connections": 1,
                "max_subscriptions": 1,
                "data_delay": 15,  # seconds
            },
            SubscriptionTier.PLUS: {
                "max_connections": 5,
                "max_subscriptions": 10,
                "data_delay": 0,
            },
            SubscriptionTier.PRO: {
                "max_connections": 10,
                "max_subscriptions": float('inf'),
                "data_delay": 0,
            },
            SubscriptionTier.LIFETIME: {
                "max_connections": 10,
                "max_subscriptions": float('inf'),
                "data_delay": 0,
            }
        }

    def get_tier_limits(self, tier: SubscriptionTier) -> dict:
        """Get limits for a subscription tier"""
        return self.tier_limits.get(tier, self.tier_limits[SubscriptionTier.STARTED])

class WebSocketManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocketConnection] = {}
        self.connection_locks: Dict[str, asyncio.Lock] = {}
        self.is_initialized: bool = False

    async def initialize(self) -> bool:
        """Initialize the WebSocket manager"""
        try:
            logger.info("Initializing WebSocket manager...")
            
            # Clear any stale connections in the database
            db = SessionLocal()
            try:
                stale_connections = db.query(WebSocketConnection).filter(
                    WebSocketConnection.is_active == True
                ).all()
                
                for conn in stale_connections:
                    conn.is_active = False
                    conn.disconnected_at = datetime.utcnow()
                
                db.commit()
                logger.info(f"Cleared {len(stale_connections)} stale connections")
                
            except Exception as db_error:
                logger.error(f"Database error during initialization: {str(db_error)}")
                raise
            finally:
                db.close()

            # Reset connection state
            self.active_connections = {}
            self.connection_locks = {}
            self.is_initialized = True
            
            logger.info("WebSocket manager initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize WebSocket manager: {str(e)}")
            self.is_initialized = False
            return False

    async def connect(self, websocket: WebSocket, account_id: str, user_id: int) -> bool:
        if account_id not in self.connection_locks:
            self.connection_locks[account_id] = asyncio.Lock()
        
        async with self.connection_locks[account_id]:
            try:
                await websocket.accept()
                
                self.active_connections[account_id] = WebSocketConnection(
                    websocket=websocket,
                    user_id=user_id,
                    connected_at=datetime.utcnow(),
                    last_heartbeat=datetime.utcnow()
                )
                
                logger.info(f"WebSocket connected for account {account_id}")
                return True
                
            except Exception as e:
                logger.error(f"WebSocket connection failed for account {account_id}: {str(e)}")
                return False

    async def disconnect(self, account_id: str):
        if account_id in self.active_connections:
            connection = self.active_connections[account_id]
            try:
                await connection.websocket.close()
            except Exception as e:
                logger.error(f"Error closing WebSocket for account {account_id}: {str(e)}")
            finally:
                del self.active_connections[account_id]

    def get_status(self) -> dict:
        """Get current WebSocket manager status"""
        return {
            "initialized": self.is_initialized,
            "active_connections": len(self.active_connections),
        }

    async def shutdown(self):
        """Shutdown the WebSocket manager"""
        try:
            # Close all active connections
            for account_id in list(self.active_connections.keys()):
                await self.disconnect(account_id)
            
            self.is_initialized = False
            logger.info("WebSocket manager shut down successfully")
            
        except Exception as e:
            logger.error(f"Error during WebSocket manager shutdown: {str(e)}")
            raise

# Global WebSocket manager instance
websocket_manager = WebSocketManager()