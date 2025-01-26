from starlette.websockets import WebSocket, WebSocketState
from datetime import datetime
from typing import Dict, Optional, Set
import asyncio
import logging
from .metrics import HeartbeatMetrics
from .websocket_config import WebSocketConfig

logger = logging.getLogger(__name__)

class ConnectionError(Exception):
    """Base exception for connection-related errors"""
    pass

class HeartbeatError(Exception):
    """Base exception for heartbeat-related errors"""
    pass

class HeartbeatMonitor:
    def __init__(self):
        self._active_connections: Dict[str, WebSocket] = {}
        self._metrics: Dict[str, HeartbeatMetrics] = {}
        self._monitoring_tasks: Dict[str, asyncio.Task] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self.config = WebSocketConfig.HEARTBEAT
        self.background_tasks: Set[asyncio.Task] = set()
        
        # Tradovate specific settings
        self.HEARTBEAT_INTERVAL = 2500  # 2.5 seconds in milliseconds
        self.MAX_MISSED_HEARTBEATS = 3
        self.HEARTBEAT_MESSAGE = '[]'
        
        # Performance tracking
        self._last_heartbeat_times: Dict[str, float] = {}
        self._missed_heartbeats: Dict[str, int] = {}

    async def start_monitoring(self, websocket: WebSocket, account_id: str, metrics: HeartbeatMetrics) -> bool:
        lock = await self.get_lock(account_id)
        async with lock:
            try:
                # Check if already monitoring
                if account_id in self._monitoring_tasks and not self._monitoring_tasks[account_id].done():
                    logger.info(f"Stopping existing monitoring for account {account_id}")
                    await self.stop_monitoring(account_id)

                # Store connection info
                self._active_connections[account_id] = websocket
                self._metrics[account_id] = metrics
                self._last_heartbeat_times[account_id] = datetime.utcnow().timestamp() * 1000
                self._missed_heartbeats[account_id] = 0

                # Create monitoring task
                task = asyncio.create_task(
                    self._monitor_connection(websocket, account_id, metrics)
                )
                task.add_done_callback(lambda t: self.background_tasks.discard(t))
                self._monitoring_tasks[account_id] = task
                self.background_tasks.add(task)

                logger.info(f"Started heartbeat monitoring for account {account_id}")
                return True

            except Exception as e:
                logger.error(f"Failed to start monitoring for account {account_id}: {str(e)}")
                await self._cleanup_connection(account_id)
                return False

    async def _monitor_connection(self, websocket: WebSocket, account_id: str, metrics: HeartbeatMetrics) -> None:
        """Monitor a specific WebSocket connection with Tradovate's requirements"""
        try:
            logger.info(f"Starting heartbeat loop for account {account_id}")
            
            while websocket.client_state != WebSocketState.DISCONNECTED:
                current_time = datetime.utcnow().timestamp() * 1000
                last_heartbeat_time = self._last_heartbeat_times.get(account_id, 0)
                time_since_last = current_time - last_heartbeat_time

                if time_since_last >= self.HEARTBEAT_INTERVAL:
                    try:
                        # Send heartbeat
                        heartbeat = {
                            "type": "heartbeat",
                            "timestamp": current_time,
                            "account_id": account_id
                        }
                        
                        await websocket.send_json(self.HEARTBEAT_MESSAGE)
                        metrics.heartbeatsSent += 1
                        
                        # Update missed heartbeats count
                        missed_count = self._missed_heartbeats.get(account_id, 0) + 1
                        self._missed_heartbeats[account_id] = missed_count
                        
                        logger.debug(
                            f"Sent heartbeat {metrics.heartbeatsSent} to account {account_id}. "
                            f"Missed count: {missed_count}"
                        )

                        # Check for too many missed heartbeats
                        if missed_count >= self.MAX_MISSED_HEARTBEATS:
                            logger.warning(
                                f"Max missed heartbeats reached for account {account_id}. "
                                f"Closing connection."
                            )
                            await self._handle_connection_failure(websocket, account_id)
                            break

                        # Update timestamp
                        self._last_heartbeat_times[account_id] = current_time

                    except Exception as e:
                        logger.error(f"Error sending heartbeat to {account_id}: {str(e)}")
                        metrics.heartbeatsFailed += 1
                        await self._handle_heartbeat_error(account_id, e, metrics)

                # Sleep for a short interval to prevent tight loop
                # Use a shorter sleep than the interval to maintain accuracy
                await asyncio.sleep(0.1)  # 100ms

        except asyncio.CancelledError:
            logger.info(f"Heartbeat monitoring cancelled for account {account_id}")
        except Exception as e:
            logger.error(f"Critical error in heartbeat monitoring for {account_id}: {str(e)}")
        finally:
            await self._handle_connection_failure(websocket, account_id)

    async def process_heartbeat_ack(self, account_id: str, ack_message: dict) -> None:
        """Process heartbeat acknowledgment from client"""
        try:
            # Reset missed heartbeats counter
            self._missed_heartbeats[account_id] = 0
            
            # Update metrics
            metrics = self._metrics.get(account_id)
            if metrics:
                metrics.lastSuccessful = datetime.utcnow()
                metrics.missedHeartbeats = 0

                logger.debug(f"Processed heartbeat ack for account {account_id}")

        except Exception as e:
            logger.error(f"Error processing heartbeat ack: {str(e)}")

    async def stop_monitoring(self, account_id: str) -> None:
        """Stop monitoring a specific connection"""
        lock = await self.get_lock(account_id)
        async with lock:
            try:
                # Cancel monitoring task
                task = self._monitoring_tasks.get(account_id)
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

                await self._cleanup_connection(account_id)
                logger.info(f"Stopped heartbeat monitoring for account {account_id}")

            except Exception as e:
                logger.error(f"Error stopping monitoring for account {account_id}: {str(e)}")

    async def _cleanup_connection(self, account_id: str) -> None:
        """Clean up connection resources"""
        self._active_connections.pop(account_id, None)
        self._metrics.pop(account_id, None)
        self._monitoring_tasks.pop(account_id, None)
        self._locks.pop(account_id, None)
        self._last_heartbeat_times.pop(account_id, None)
        self._missed_heartbeats.pop(account_id, None)

    async def get_lock(self, account_id: str) -> asyncio.Lock:
        """Get or create a lock for specific account"""
        if account_id not in self._locks:
            self._locks[account_id] = asyncio.Lock()
        return self._locks[account_id]

    def get_connection_stats(self, account_id: str) -> dict:
        """Get connection statistics"""
        metrics = self._metrics.get(account_id)
        if not metrics:
            return {"is_active": False}

        return {
            "is_active": account_id in self._active_connections,
            "total_heartbeats": metrics.heartbeatsSent,
            "missed_heartbeats": self._missed_heartbeats.get(account_id, 0),
            "last_heartbeat": self._last_heartbeat_times.get(account_id),
            "last_successful": metrics.lastSuccessful
        }

    def get_health_status(self) -> dict:
        """Get overall health status"""
        return {
            "total_connections": len(self._active_connections),
            "monitored_connections": len(self._monitoring_tasks),
            "active_tasks": len([t for t in self._monitoring_tasks.values() if not t.done()]),
            "background_tasks": len(self.background_tasks)
        }

# Create singleton instance
heartbeat_monitor = HeartbeatMonitor()