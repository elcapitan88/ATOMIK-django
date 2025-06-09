"""
Graceful Shutdown and Worker Recovery System

Handles worker crashes gracefully, ensures proper cleanup of resources,
and provides recovery mechanisms for interrupted trading operations.
"""

import signal
import asyncio
import logging
import time
import json
from typing import Dict, Any, List, Optional, Callable, Set
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
from threading import Thread
import weakref

from ..core.correlation import CorrelationLogger, CorrelationManager
from ..core.redis_manager import get_redis_connection
from redis.exceptions import RedisError

logger = CorrelationLogger(__name__)

@dataclass
class WorkerTask:
    """Represents an active worker task that needs cleanup on shutdown"""
    task_id: str
    task_type: str  # e.g., "webhook_processing", "strategy_execution", "order_monitoring"
    correlation_id: Optional[str]
    started_at: float
    context_data: Dict[str, Any] = field(default_factory=dict)
    cleanup_callback: Optional[Callable] = None

class GracefulShutdownManager:
    """
    Manages graceful shutdown of the application and recovery from worker crashes
    """
    
    def __init__(self):
        self._active_tasks: Dict[str, WorkerTask] = {}
        self._shutdown_event = asyncio.Event()
        self._cleanup_callbacks: List[Callable] = []
        self._is_shutting_down = False
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._worker_id = f"worker_{int(time.time())}_{id(self)}"
        self._lock = asyncio.Lock()
        
        # Register signal handlers
        self._register_signal_handlers()
        
    def _register_signal_handlers(self):
        """Register signal handlers for graceful shutdown"""
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating graceful shutdown")
            asyncio.create_task(self.shutdown())
        
        # Register handlers for common termination signals
        for sig in [signal.SIGTERM, signal.SIGINT]:
            try:
                signal.signal(sig, signal_handler)
            except ValueError:
                # May not be supported on all platforms
                pass
    
    async def start(self):
        """Start the graceful shutdown manager"""
        logger.info(f"Starting graceful shutdown manager for worker {self._worker_id}")
        
        # Start heartbeat to track worker health
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        
        # Check for orphaned tasks from previous worker crashes
        await self._recover_orphaned_tasks()
    
    async def stop(self):
        """Stop the graceful shutdown manager"""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
    
    @asynccontextmanager
    async def track_task(
        self, 
        task_type: str, 
        task_id: Optional[str] = None,
        cleanup_callback: Optional[Callable] = None,
        **context_data
    ):
        """
        Context manager to track active tasks for graceful shutdown
        
        Usage:
            async with shutdown_manager.track_task("webhook_processing", webhook_id="123"):
                # Your task code here
                await process_webhook()
        """
        if task_id is None:
            task_id = f"{task_type}_{int(time.time() * 1000)}"
        
        correlation_id = CorrelationManager.get_correlation_id()
        
        task = WorkerTask(
            task_id=task_id,
            task_type=task_type,
            correlation_id=correlation_id,
            started_at=time.time(),
            context_data=context_data,
            cleanup_callback=cleanup_callback
        )
        
        # Register task
        async with self._lock:
            self._active_tasks[task_id] = task
            await self._persist_active_task(task)
        
        logger.info(f"Started tracking task: {task_type} [{task_id}]")
        
        try:
            yield task
        except Exception as e:
            logger.error(f"Task failed: {task_type} [{task_id}] - {str(e)}")
            raise
        finally:
            # Unregister task
            async with self._lock:
                if task_id in self._active_tasks:
                    del self._active_tasks[task_id]
                await self._remove_persisted_task(task_id)
            
            logger.info(f"Finished tracking task: {task_type} [{task_id}]")
    
    async def _persist_active_task(self, task: WorkerTask):
        """Persist active task info to Redis for crash recovery"""
        try:
            with get_redis_connection() as redis_client:
                if not redis_client:
                    return
                
                task_key = f"active_task:{self._worker_id}:{task.task_id}"
                task_data = {
                    "task_id": task.task_id,
                    "task_type": task.task_type,
                    "correlation_id": task.correlation_id,
                    "started_at": task.started_at,
                    "worker_id": self._worker_id,
                    "context_data": task.context_data
                }
                
                # Store with TTL to handle worker crashes
                redis_client.setex(task_key, 300, json.dumps(task_data))  # 5 minute TTL
                
        except RedisError as e:
            logger.warning(f"Failed to persist active task: {e}")
        except Exception as e:
            logger.error(f"Unexpected error persisting active task: {e}")
    
    async def _remove_persisted_task(self, task_id: str):
        """Remove persisted task info from Redis"""
        try:
            with get_redis_connection() as redis_client:
                if not redis_client:
                    return
                
                task_key = f"active_task:{self._worker_id}:{task_id}"
                redis_client.delete(task_key)
                
        except RedisError as e:
            logger.warning(f"Failed to remove persisted task: {e}")
        except Exception as e:
            logger.error(f"Unexpected error removing persisted task: {e}")
    
    async def _heartbeat_loop(self):
        """Send periodic heartbeats to track worker health"""
        while not self._shutdown_event.is_set():
            try:
                await self._send_heartbeat()
                await asyncio.sleep(30)  # Heartbeat every 30 seconds
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}")
                await asyncio.sleep(5)  # Shorter retry interval on error
    
    async def _send_heartbeat(self):
        """Send heartbeat to Redis"""
        try:
            with get_redis_connection() as redis_client:
                if not redis_client:
                    return
                
                heartbeat_key = f"worker_heartbeat:{self._worker_id}"
                heartbeat_data = {
                    "worker_id": self._worker_id,
                    "timestamp": time.time(),
                    "active_tasks": len(self._active_tasks),
                    "task_types": list(set(task.task_type for task in self._active_tasks.values()))
                }
                
                # Store heartbeat with TTL
                redis_client.setex(heartbeat_key, 60, json.dumps(heartbeat_data))
                
        except RedisError as e:
            logger.warning(f"Failed to send heartbeat: {e}")
        except Exception as e:
            logger.error(f"Unexpected error sending heartbeat: {e}")
    
    async def _recover_orphaned_tasks(self):
        """Check for orphaned tasks from crashed workers"""
        try:
            with get_redis_connection() as redis_client:
                if not redis_client:
                    return
                
                # Find all active task keys
                task_pattern = "active_task:*"
                task_keys = redis_client.keys(task_pattern)
                
                orphaned_tasks = []
                current_time = time.time()
                
                for task_key in task_keys:
                    try:
                        task_data_raw = redis_client.get(task_key)
                        if not task_data_raw:
                            continue
                        
                        task_data = json.loads(task_data_raw)
                        worker_id = task_data.get("worker_id")
                        started_at = task_data.get("started_at", 0)
                        
                        # Check if worker is still alive
                        heartbeat_key = f"worker_heartbeat:{worker_id}"
                        heartbeat_data = redis_client.get(heartbeat_key)
                        
                        if not heartbeat_data:
                            # Worker is dead, task is orphaned
                            task_age = current_time - started_at
                            if task_age > 120:  # Task running for more than 2 minutes without heartbeat
                                orphaned_tasks.append({
                                    "key": task_key,
                                    "data": task_data,
                                    "age_seconds": task_age
                                })
                    
                    except (json.JSONDecodeError, KeyError) as e:
                        logger.warning(f"Invalid task data in Redis key {task_key}: {e}")
                
                if orphaned_tasks:
                    logger.warning(f"Found {len(orphaned_tasks)} orphaned tasks from crashed workers")
                    await self._handle_orphaned_tasks(orphaned_tasks)
                
        except RedisError as e:
            logger.warning(f"Failed to check for orphaned tasks: {e}")
        except Exception as e:
            logger.error(f"Unexpected error checking for orphaned tasks: {e}")
    
    async def _handle_orphaned_tasks(self, orphaned_tasks: List[Dict[str, Any]]):
        """Handle recovery of orphaned tasks"""
        for orphan in orphaned_tasks:
            task_data = orphan["data"]
            task_key = orphan["key"]
            
            logger.warning(
                f"Orphaned task detected: {task_data.get('task_type')} "
                f"[{task_data.get('task_id')}] from worker {task_data.get('worker_id')}, "
                f"age: {orphan['age_seconds']:.0f}s"
            )
            
            # Clean up the orphaned task entry
            try:
                with get_redis_connection() as redis_client:
                    if redis_client:
                        redis_client.delete(task_key)
            except Exception as e:
                logger.error(f"Failed to clean up orphaned task key {task_key}: {e}")
            
            # TODO: Add specific recovery logic based on task type
            # For now, we just log and clean up
            # In the future, could implement:
            # - Retry mechanism for failed webhooks
            # - Rollback incomplete trades
            # - Notify monitoring systems
    
    def add_cleanup_callback(self, callback: Callable):
        """Add callback to be executed during shutdown"""
        self._cleanup_callbacks.append(callback)
    
    async def shutdown(self):
        """Initiate graceful shutdown"""
        if self._is_shutting_down:
            return
        
        self._is_shutting_down = True
        self._shutdown_event.set()
        
        logger.info("Starting graceful shutdown process")
        
        # Wait for active tasks to complete (with timeout)
        shutdown_timeout = 30  # 30 seconds to complete active tasks
        start_time = time.time()
        
        while self._active_tasks and (time.time() - start_time) < shutdown_timeout:
            logger.info(f"Waiting for {len(self._active_tasks)} active tasks to complete...")
            await asyncio.sleep(1)
        
        if self._active_tasks:
            logger.warning(f"Forcefully terminating {len(self._active_tasks)} remaining tasks")
            for task in self._active_tasks.values():
                if task.cleanup_callback:
                    try:
                        await task.cleanup_callback()
                    except Exception as e:
                        logger.error(f"Error in task cleanup callback: {e}")
        
        # Execute cleanup callbacks
        for callback in self._cleanup_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback()
                else:
                    callback()
            except Exception as e:
                logger.error(f"Error in cleanup callback: {e}")
        
        # Stop heartbeat
        await self.stop()
        
        logger.info("Graceful shutdown completed")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current shutdown manager statistics"""
        return {
            "worker_id": self._worker_id,
            "is_shutting_down": self._is_shutting_down,
            "active_tasks": len(self._active_tasks),
            "task_summary": {
                task_type: len([t for t in self._active_tasks.values() if t.task_type == task_type])
                for task_type in set(task.task_type for task in self._active_tasks.values())
            },
            "cleanup_callbacks": len(self._cleanup_callbacks)
        }

# Global graceful shutdown manager instance
shutdown_manager = GracefulShutdownManager()