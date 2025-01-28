from datetime import datetime
from typing import Dict, Optional, Set
import asyncio
import logging
from starlette.websockets import WebSocket, WebSocketState
from .metrics import HeartbeatMetrics

logger = logging.getLogger(__name__)

class HeartbeatMonitor:
    """
    Monitors WebSocket connection health by tracking client heartbeats.
    Only monitors client-initiated heartbeats, does not send heartbeats.
    """
    
    def __init__(self):
        # Active connections being monitored
        self._active_connections: Dict[str, WebSocket] = {}
        
        # Track message timestamps and metrics
        self._last_message_times: Dict[str, float] = {}
        self._metrics: Dict[str, HeartbeatMetrics] = {}
        
        # Connection state tracking
        self._monitoring_tasks: Dict[str, asyncio.Task] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self.background_tasks: Set[asyncio.Task] = set()
        
        # Constants specific to Tradovate
        self.HEARTBEAT_THRESHOLD = 2500  # Expected heartbeat every 2.5s (in ms)
        self.MAX_MISSED_HEARTBEATS = 3   # Close connection after 3 missed heartbeats

    async def start_monitoring(
        self, 
        websocket: WebSocket, 
        account_id: str, 
        metrics: HeartbeatMetrics
    ) -> bool:
        """Start monitoring a WebSocket connection"""
        lock = await self.get_lock(account_id)
        async with lock:
            try:
                # Cancel existing monitoring if any
                if account_id in self._monitoring_tasks and not self._monitoring_tasks[account_id].done():
                    logger.info(f"Stopping existing monitoring for account {account_id}")
                    await self.stop_monitoring(account_id)

                # Initialize monitoring state
                self._active_connections[account_id] = websocket
                self._metrics[account_id] = metrics
                self._last_message_times[account_id] = datetime.utcnow().timestamp() * 1000

                # Start monitoring task
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

    async def process_heartbeat(self, account_id: str) -> None:
        """Process a received heartbeat from the client"""
        try:
            current_time = datetime.utcnow().timestamp() * 1000
            self._last_message_times[account_id] = current_time
            
            if account_id in self._metrics:
                await self._metrics[account_id].record_heartbeat()
                logger.debug(f"Processed heartbeat for account {account_id}")
                
        except Exception as e:
            logger.error(f"Error processing heartbeat for {account_id}: {str(e)}")

    async def _monitor_connection(
        self, 
        websocket: WebSocket, 
        account_id: str, 
        metrics: HeartbeatMetrics
    ) -> None:
        """Monitor connection health"""
        missed_heartbeats = 0
        
        try:
            while websocket.client_state == WebSocketState.CONNECTED:
                current_time = datetime.utcnow().timestamp() * 1000
                last_time = self._last_message_times.get(account_id, 0)
                time_since_last = current_time - last_time

                if time_since_last >= self.HEARTBEAT_THRESHOLD:
                    missed_heartbeats += 1
                    await metrics.record_missed()
                    
                    logger.warning(
                        f"Missed heartbeat for account {account_id}. "
                        f"Count: {missed_heartbeats}/{self.MAX_MISSED_HEARTBEATS}"
                    )
                    
                    if missed_heartbeats >= self.MAX_MISSED_HEARTBEATS:
                        logger.error(f"Connection stale for account {account_id}")
                        await self._handle_connection_failure(websocket, account_id)
                        break
                else:
                    missed_heartbeats = 0

                # Check every 100ms
                await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            logger.info(f"Monitoring cancelled for account {account_id}")
        except Exception as e:
            logger.error(f"Error monitoring account {account_id}: {str(e)}")
        finally:
            await self._handle_connection_failure(websocket, account_id)

    async def _handle_connection_failure(self, websocket: WebSocket, account_id: str) -> None:
        """Handle connection failure"""
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.close(code=4000, reason="Connection stale")
                logger.info(f"Closed stale connection for account {account_id}")
            
            await self._cleanup_connection(account_id)
            
        except Exception as e:
            logger.error(f"Error handling connection failure for {account_id}: {str(e)}")

    async def stop_monitoring(self, account_id: str) -> None:
        """Stop monitoring a connection"""
        lock = await self.get_lock(account_id)
        async with lock:
            try:
                task = self._monitoring_tasks.get(account_id)
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

                await self._cleanup_connection(account_id)
                logger.info(f"Stopped monitoring for account {account_id}")

            except Exception as e:
                logger.error(f"Error stopping monitoring for account {account_id}: {str(e)}")

    async def _cleanup_connection(self, account_id: str) -> None:
        """Clean up connection resources"""
        self._active_connections.pop(account_id, None)
        self._last_message_times.pop(account_id, None)
        self._metrics.pop(account_id, None)
        self._monitoring_tasks.pop(account_id, None)
        self._locks.pop(account_id, None)

    async def get_lock(self, account_id: str) -> asyncio.Lock:
        """Get or create a lock for specific account"""
        if account_id not in self._locks:
            self._locks[account_id] = asyncio.Lock()
        return self._locks[account_id]

    def get_connection_stats(self, account_id: str) -> dict:
        """Get connection statistics"""
        metrics = self._metrics.get(account_id)
        return {
            "is_active": account_id in self._active_connections,
            "last_message": self._last_message_times.get(account_id),
            "metrics": metrics.get_metrics() if metrics else None
        }

    def get_health_status(self) -> dict:
        """Get overall monitoring health status"""
        return {
            "total_connections": len(self._active_connections),
            "monitored_connections": len(self._monitoring_tasks),
            "active_tasks": len([t for t in self._monitoring_tasks.values() if not t.done()]),
            "background_tasks": len(self.background_tasks)
        }

# Create singleton instance
heartbeat_monitor = HeartbeatMonitor()