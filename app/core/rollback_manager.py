"""
Rollback Manager for Failed Trading Operations

Provides mechanisms to safely rollback partial transactions and maintain
data consistency when trading operations fail partway through execution.
"""

import asyncio
import logging
import time
import json
from typing import Dict, Any, List, Optional, Callable, Awaitable, Union
from dataclasses import dataclass, field
from enum import Enum
from contextlib import asynccontextmanager

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from ..core.correlation import CorrelationLogger, CorrelationManager
from ..core.redis_manager import get_redis_connection
from ..db.session import get_db_context
from redis.exceptions import RedisError

logger = CorrelationLogger(__name__)

class RollbackAction(Enum):
    """Types of rollback actions"""
    DATABASE_ROLLBACK = "database_rollback"
    BROKER_ORDER_CANCEL = "broker_order_cancel"
    CUSTOM_CLEANUP = "custom_cleanup"
    NOTIFICATION_SEND = "notification_send"

@dataclass
class RollbackStep:
    """Represents a single rollback step"""
    action: RollbackAction
    description: str
    callback: Callable[..., Awaitable[bool]]
    args: tuple = field(default_factory=tuple)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    rollback_order: int = 0  # Lower numbers executed first
    max_retries: int = 3
    executed: bool = False
    success: bool = False

@dataclass
class RollbackContext:
    """Context for managing rollback operations"""
    transaction_id: str
    operation_type: str
    correlation_id: Optional[str]
    started_at: float
    steps: List[RollbackStep] = field(default_factory=list)
    completed: bool = False
    success: bool = False
    error_message: Optional[str] = None

class RollbackManager:
    """
    Manages rollback operations for failed trading transactions
    """
    
    def __init__(self):
        self._active_contexts: Dict[str, RollbackContext] = {}
        self._lock = asyncio.Lock()
    
    @asynccontextmanager
    async def transaction_context(
        self, 
        operation_type: str,
        transaction_id: Optional[str] = None
    ):
        """
        Context manager for transactional operations with rollback support
        
        Usage:
            async with rollback_manager.transaction_context("strategy_execution") as ctx:
                # Add rollback steps as needed
                await ctx.add_rollback_step(...)
                
                # Your operation code here
                await execute_strategy()
                
                # If we reach here, transaction succeeded
        """
        if transaction_id is None:
            transaction_id = f"{operation_type}_{int(time.time() * 1000)}"
        
        correlation_id = CorrelationManager.get_correlation_id()
        
        context = RollbackContext(
            transaction_id=transaction_id,
            operation_type=operation_type,
            correlation_id=correlation_id,
            started_at=time.time()
        )
        
        async with self._lock:
            self._active_contexts[transaction_id] = context
        
        logger.info(f"Started transaction context: {operation_type} [{transaction_id}]")
        
        try:
            yield TransactionContext(context, self)
            
            # Transaction completed successfully
            context.completed = True
            context.success = True
            logger.info(f"Transaction completed successfully: {operation_type} [{transaction_id}]")
            
        except Exception as e:
            # Transaction failed, execute rollback
            context.completed = True
            context.success = False
            context.error_message = str(e)
            
            logger.error(f"Transaction failed: {operation_type} [{transaction_id}] - {str(e)}")
            
            # Execute rollback steps
            await self._execute_rollback(context)
            raise
            
        finally:
            async with self._lock:
                if transaction_id in self._active_contexts:
                    del self._active_contexts[transaction_id]
    
    async def _execute_rollback(self, context: RollbackContext):
        """Execute all rollback steps for a failed transaction"""
        if not context.steps:
            logger.info(f"No rollback steps to execute for transaction {context.transaction_id}")
            return
        
        logger.warning(f"Executing rollback for transaction {context.transaction_id} with {len(context.steps)} steps")
        
        # Sort steps by rollback order (lower numbers first)
        sorted_steps = sorted(context.steps, key=lambda s: s.rollback_order)
        
        rollback_errors = []
        
        for step in sorted_steps:
            try:
                logger.info(f"Executing rollback step: {step.description}")
                
                # Retry logic for rollback steps
                success = False
                for attempt in range(step.max_retries):
                    try:
                        success = await step.callback(*step.args, **step.kwargs)
                        if success:
                            break
                        
                        if attempt < step.max_retries - 1:
                            logger.warning(f"Rollback step attempt {attempt + 1} failed, retrying: {step.description}")
                            await asyncio.sleep(1 * (attempt + 1))  # Exponential backoff
                        
                    except Exception as e:
                        logger.error(f"Rollback step attempt {attempt + 1} error: {step.description} - {str(e)}")
                        if attempt == step.max_retries - 1:
                            raise
                        await asyncio.sleep(1 * (attempt + 1))
                
                step.executed = True
                step.success = success
                
                if success:
                    logger.info(f"Rollback step completed successfully: {step.description}")
                else:
                    error_msg = f"Rollback step failed after {step.max_retries} attempts: {step.description}"
                    logger.error(error_msg)
                    rollback_errors.append(error_msg)
                
            except Exception as e:
                step.executed = True
                step.success = False
                error_msg = f"Rollback step threw exception: {step.description} - {str(e)}"
                logger.error(error_msg)
                rollback_errors.append(error_msg)
        
        # Log rollback summary
        successful_steps = sum(1 for step in sorted_steps if step.success)
        total_steps = len(sorted_steps)
        
        if rollback_errors:
            logger.error(f"Rollback completed with errors: {successful_steps}/{total_steps} steps successful")
            for error in rollback_errors:
                logger.error(f"Rollback error: {error}")
        else:
            logger.info(f"Rollback completed successfully: {successful_steps}/{total_steps} steps successful")
    
    async def force_rollback(self, transaction_id: str) -> bool:
        """Force rollback of an active transaction (admin operation)"""
        async with self._lock:
            if transaction_id not in self._active_contexts:
                logger.warning(f"Cannot force rollback - transaction not found: {transaction_id}")
                return False
            
            context = self._active_contexts[transaction_id]
        
        logger.warning(f"Force rolling back transaction: {transaction_id}")
        
        context.completed = True
        context.success = False
        context.error_message = "Force rollback requested"
        
        await self._execute_rollback(context)
        return True
    
    def get_active_transactions(self) -> Dict[str, Dict[str, Any]]:
        """Get information about active transactions"""
        return {
            tid: {
                "transaction_id": ctx.transaction_id,
                "operation_type": ctx.operation_type,
                "correlation_id": ctx.correlation_id,
                "started_at": ctx.started_at,
                "duration": time.time() - ctx.started_at,
                "rollback_steps": len(ctx.steps),
                "completed": ctx.completed,
                "success": ctx.success
            }
            for tid, ctx in self._active_contexts.items()
        }

class TransactionContext:
    """
    Helper class for managing rollback steps within a transaction context
    """
    
    def __init__(self, context: RollbackContext, manager: RollbackManager):
        self.context = context
        self.manager = manager
        self._db_session: Optional[Session] = None
    
    async def add_rollback_step(
        self,
        action: RollbackAction,
        description: str,
        callback: Callable[..., Awaitable[bool]],
        *args,
        rollback_order: int = 0,
        max_retries: int = 3,
        **kwargs
    ):
        """Add a rollback step to be executed if the transaction fails"""
        step = RollbackStep(
            action=action,
            description=description,
            callback=callback,
            args=args,
            kwargs=kwargs,
            rollback_order=rollback_order,
            max_retries=max_retries
        )
        
        self.context.steps.append(step)
        logger.debug(f"Added rollback step: {description} (order: {rollback_order})")
    
    @asynccontextmanager
    async def database_transaction(self):
        """
        Context manager for database transactions with automatic rollback registration
        """
        async with get_db_context() as db:
            self._db_session = db
            
            # Register database rollback step
            await self.add_rollback_step(
                action=RollbackAction.DATABASE_ROLLBACK,
                description="Rollback database transaction",
                callback=self._rollback_database_transaction,
                rollback_order=0  # Database rollbacks should happen first
            )
            
            try:
                # Start transaction
                db.begin()
                logger.debug("Started database transaction")
                yield db
                
                # If we reach here, commit the transaction
                db.commit()
                logger.debug("Committed database transaction")
                
            except Exception as e:
                # Transaction will be rolled back by rollback step
                logger.error(f"Database transaction failed: {str(e)}")
                raise
    
    async def _rollback_database_transaction(self) -> bool:
        """Rollback the database transaction"""
        if self._db_session:
            try:
                self._db_session.rollback()
                logger.info("Database transaction rolled back successfully")
                return True
            except SQLAlchemyError as e:
                logger.error(f"Failed to rollback database transaction: {str(e)}")
                return False
        
        logger.warning("No database session to rollback")
        return True
    
    async def add_broker_order_cancel(
        self,
        broker_instance,
        account,
        order_id: str,
        rollback_order: int = 1
    ):
        """Add broker order cancellation to rollback steps"""
        await self.add_rollback_step(
            action=RollbackAction.BROKER_ORDER_CANCEL,
            description=f"Cancel broker order: {order_id}",
            callback=self._cancel_broker_order,
            rollback_order=rollback_order,
            broker_instance=broker_instance,
            account=account,
            order_id=order_id
        )
    
    async def _cancel_broker_order(self, broker_instance, account, order_id: str) -> bool:
        """Cancel a broker order"""
        try:
            result = await broker_instance.cancel_order(account, order_id)
            if result.get("status") == "cancelled":
                logger.info(f"Successfully cancelled broker order: {order_id}")
                return True
            else:
                logger.warning(f"Failed to cancel broker order: {order_id} - {result}")
                return False
        except Exception as e:
            logger.error(f"Error cancelling broker order {order_id}: {str(e)}")
            return False
    
    async def add_notification(
        self,
        message: str,
        notification_type: str = "rollback_alert",
        rollback_order: int = 99  # Notifications should happen last
    ):
        """Add notification to rollback steps"""
        await self.add_rollback_step(
            action=RollbackAction.NOTIFICATION_SEND,
            description=f"Send {notification_type} notification",
            callback=self._send_notification,
            message=message,
            notification_type=notification_type,
            rollback_order=rollback_order
        )
    
    async def _send_notification(self, message: str, notification_type: str) -> bool:
        """Send a notification (placeholder implementation)"""
        logger.warning(f"ROLLBACK NOTIFICATION [{notification_type}]: {message}")
        
        # TODO: Implement actual notification sending
        # Could integrate with email service, Slack, monitoring systems, etc.
        
        return True

# Global rollback manager instance
rollback_manager = RollbackManager()