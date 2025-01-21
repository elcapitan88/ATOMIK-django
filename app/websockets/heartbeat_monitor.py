import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional, Set
from starlette.websockets import WebSocketState
from fastapi import WebSocket

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

    async def start_monitoring(self, websocket: WebSocket, account_id: str, metrics: HeartbeatMetrics) -> bool:
        """Start monitoring a WebSocket connection"""
        lock = await self.get_lock(account_id)
        async with lock:
            try:
                # Check if already monitoring
                if account_id in self._monitoring_tasks and not self._monitoring_tasks[account_id].done():
                    logger.warning(f"Already monitoring account {account_id}")
                    return False

                # Store connection info
                self._active_connections[account_id] = websocket
                self._metrics[account_id] = metrics

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
        """Monitor a specific WebSocket connection"""
        try:
            logger.info(f"Starting heartbeat loop for account {account_id}")
            while True:
                if websocket.client_state == WebSocketState.DISCONNECTED:
                    logger.info(f"WebSocket disconnected for account {account_id}, stopping heartbeat")
                    break

                try:
                    current_time = datetime.utcnow()
                    # Generate and send heartbeat
                    heartbeat = {
                        "type": "heartbeat",
                        "sequence": metrics.totalHeartbeats + 1,
                        "timestamp": current_time.isoformat(),
                        "account_id": account_id,
                        "stats": {
                            "total_sent": metrics.totalHeartbeats,
                            "missed": metrics.missedHeartbeats
                        }
                    }

                    logger.info(f"Sending heartbeat {heartbeat['sequence']} to account {account_id}")
                    await websocket.send_json(heartbeat)
                    metrics.totalHeartbeats += 1
                    metrics.lastHeartbeat = current_time
                    
                    logger.info(f"Heartbeat {heartbeat['sequence']} sent successfully to account {account_id}")

                except RuntimeError as runtime_error:
                    if "Cannot call 'send' once a close message has been sent" in str(runtime_error):
                        logger.info(f"Connection already closed for account {account_id}")
                        break
                    raise

                except Exception as send_error:
                    await self._handle_heartbeat_error(account_id, send_error, metrics)
                    if metrics.missedHeartbeats >= self.config['MAX_MISSED']:
                        break

                # Wait for next interval
                await asyncio.sleep(self.config['INTERVAL'] / 1000)  # Convert to seconds

        except asyncio.CancelledError:
            logger.info(f"Heartbeat monitoring cancelled for account {account_id}")
        except Exception as e:
            logger.error(f"Critical error in heartbeat monitoring for {account_id}: {str(e)}")
        finally:
            await self._handle_connection_failure(websocket, account_id)

    async def _handle_heartbeat_error(self, account_id: str, error: Exception, metrics: HeartbeatMetrics) -> None:
        """Handle errors during heartbeat sending"""
        try:
            logger.error(f"Heartbeat error for account {account_id}: {str(error)}")
            
            metrics.missedHeartbeats += 1
            metrics.lastFailure = datetime.utcnow()
            
            if metrics.missedHeartbeats >= self.config['MAX_MISSED']:
                logger.warning(f"Max missed heartbeats reached for account {account_id}")
                websocket = self._active_connections.get(account_id)
                if websocket and websocket.client_state != WebSocketState.DISCONNECTED:
                    await self._handle_connection_failure(websocket, account_id)

        except Exception as e:
            logger.error(f"Error handling heartbeat error: {str(e)}")

    async def _handle_connection_failure(self, websocket: WebSocket, account_id: str) -> None:
        """Handle connection failure scenarios"""
        try:
            if websocket.client_state != WebSocketState.DISCONNECTED:
                # Try to send failure notification
                try:
                    await websocket.send_json({
                        "type": "error",
                        "code": "heartbeat_failure",
                        "message": "Connection terminated due to heartbeat failure",
                        "timestamp": datetime.utcnow().isoformat()
                    })
                except Exception:
                    pass  # Ignore send errors during failure handling

                # Close the connection
                try:
                    await websocket.close(code=4000)  # Custom close code for heartbeat failure
                except Exception:
                    pass  # Ignore close errors

            await self._cleanup_connection(account_id)

        except Exception as e:
            logger.error(f"Error handling connection failure: {str(e)}")

    async def process_heartbeat_ack(self, account_id: str, ack_message: dict) -> None:
        """Process heartbeat acknowledgment from client"""
        try:
            metrics = self._metrics.get(account_id)
            if metrics:
                metrics.lastSuccessful = datetime.utcnow()
                metrics.missedHeartbeats = 0  # Reset missed count on successful ack

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
        try:
            self._monitoring_tasks.pop(account_id, None)
            self._active_connections.pop(account_id, None)
            self._metrics.pop(account_id, None)
            self._locks.pop(account_id, None)
        except Exception as e:
            logger.error(f"Error cleaning up connection {account_id}: {str(e)}")

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
            "total_heartbeats": metrics.totalHeartbeats,
            "missed_heartbeats": metrics.missedHeartbeats,
            "last_heartbeat": metrics.lastHeartbeat,
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