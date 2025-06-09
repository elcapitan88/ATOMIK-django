from typing import Dict, Any
from datetime import datetime
from decimal import Decimal
import logging
import time
import traceback
import asyncio
from fastapi import HTTPException
from sqlalchemy.orm import Session
from ..models.strategy import ActivatedStrategy
from ..models.broker import BrokerAccount

from ..models.strategy import ActivatedStrategy
from ..models.broker import BrokerAccount, BrokerCredentials
from ..core.brokers.base import BaseBroker
from fastapi import HTTPException
# Import the ticker utilities
from ..utils.ticker_utils import validate_ticker, get_contract_ticker, get_display_ticker
# Import distributed locking
from .distributed_lock import AccountLockManager
# Import enhanced error handling
from ..core.enhanced_logging import get_enhanced_logger, logging_context, operation_logging
from ..core.alert_manager import TradingAlerts
from ..core.circuit_breaker import circuit_breaker_manager, CircuitBreakerOpenError
from ..core.rollback_manager import rollback_manager
from ..core.graceful_shutdown import shutdown_manager

logger = get_enhanced_logger(__name__)

class OrderPool:
    def __init__(self, db: Session, strategy_processor):
        self.db = db
        self.strategy_processor = strategy_processor
        self.pool = []
        self.lock = asyncio.Lock()
        self.window_size = 0.1  # 100ms pooling window
        self.max_batch_size = 10
        self.processing = False

    async def add_orders(self, strategy: ActivatedStrategy, signal_data: Dict[str, Any]):
        """Add orders to pool and process if window is full"""
        async with self.lock:
            if strategy.strategy_type == 'multiple':
                try:
                    # Process leader order immediately
                    leader_order = {
                        'account_id': strategy.leader_account_id,
                        'quantity': strategy.leader_quantity,
                        'is_leader': True,
                        'strategy': strategy,
                        'signal_data': signal_data
                    }
                    
                    logger.info(f"Processing leader order for strategy {strategy.id}")
                    await self._execute_leader_order(leader_order)

                    # Add follower orders to pool
                    for follower in strategy.follower_accounts_with_quantities:
                        follower_order = {
                            'account_id': follower.account_id,
                            'quantity': strategy.get_follower_quantity(follower.account_id),
                            'is_leader': False,
                            'strategy': strategy,
                            'signal_data': signal_data
                        }
                        self.pool.append(follower_order)
                        logger.info(f"Added follower order to pool for account {follower.account_id}")

                    # Start pool processing if not already running
                    if not self.processing:
                        asyncio.create_task(self._process_pool())

                except Exception as e:
                    logger.error(f"Error adding orders to pool: {str(e)}")
                    raise

    async def _execute_leader_order(self, order: Dict):
        """Execute leader order with distributed locking"""
        try:
            strategy_dict = {
                'user_id': order['strategy'].user_id,
                'strategy_type': 'single',
                'webhook_id': order['strategy'].webhook_id,
                'ticker': order['strategy'].ticker,
                'account_id': order['account_id'],
                'quantity': order['quantity'],
                'is_active': order['strategy'].is_active
            }
            
            leader_strategy = ActivatedStrategy(**strategy_dict)
            result = await self.strategy_processor._execute_single_account_strategy(
                leader_strategy,
                order['signal_data']
            )
            
            logger.info(f"Leader order execution result: {result}")
            return result

        except Exception as e:
            logger.error(f"Leader order execution failed: {str(e)}")
            raise

    async def _process_pool(self):
        """Process pooled orders"""
        try:
            self.processing = True
            while self.pool:
                # Get batch of orders
                async with self.lock:
                    batch = self.pool[:self.max_batch_size]
                    self.pool = self.pool[self.max_batch_size:]

                if batch:
                    logger.info(f"Processing batch of {len(batch)} orders")
                    start_time = time.time()
                    
                    # Execute batch concurrently
                    tasks = []
                    for order in batch:
                        strategy_dict = {
                            'user_id': order['strategy'].user_id,
                            'strategy_type': 'single',
                            'webhook_id': order['strategy'].webhook_id,
                            'ticker': order['strategy'].ticker,
                            'account_id': order['account_id'],
                            'quantity': order['quantity'],
                            'is_active': order['strategy'].is_active
                        }
                        
                        follower_strategy = ActivatedStrategy(**strategy_dict)
                        tasks.append(
                            self.strategy_processor._execute_single_account_strategy(
                                follower_strategy,
                                order['signal_data']
                            )
                        )

                    if tasks:
                        results = await asyncio.gather(*tasks, return_exceptions=True)
                        
                        # Log any errors from batch execution
                        for i, result in enumerate(results):
                            if isinstance(result, Exception):
                                logger.error(f"Error executing order {batch[i]['account_id']}: {str(result)}")
                    
                    execution_time = time.time() - start_time
                    logger.info(f"Batch processing completed in {execution_time:.3f} seconds")

                # Small delay between batches
                await asyncio.sleep(self.window_size)

        except Exception as e:
            logger.error(f"Pool processing error: {str(e)}")
        finally:
            self.processing = False

    def get_pool_stats(self) -> Dict[str, Any]:
        """Get current pool statistics"""
        return {
            "pool_size": len(self.pool),
            "processing": self.processing,
            "timestamp": datetime.utcnow().isoformat()
        }

class StrategyProcessor:
    def __init__(self, db: Session):
        self.db = db
        self._lock = asyncio.Lock()
        self.order_pool = OrderPool(db, self)

    async def execute_strategy(
        self,
        strategy: ActivatedStrategy,
        signal_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute trading strategy based on incoming signal"""
        try:
            if not strategy.is_active:
                logger.warning(f"Strategy {strategy.id} is not active")
                return {"status": "skipped", "reason": "Strategy is not active"}

            # Validate the ticker in the strategy
            valid, contract_ticker = validate_ticker(strategy.ticker)
            if not valid:
                error_msg = f"Invalid ticker format: {strategy.ticker}"
                logger.error(error_msg)
                strategy.failed_trades += 1
                self.db.commit()
                return {"status": "error", "reason": error_msg}
            
            # Update signal_data with the validated contract ticker
            signal_data = signal_data.copy()  # Create a copy to avoid modifying the original
            
            # Log the ticker transformation
            logger.info(f"Transforming ticker from {strategy.ticker} to {contract_ticker}")
            
            if strategy.strategy_type == 'single':
                return await self._execute_single_account_strategy(strategy, signal_data)
            else:
                await self.order_pool.add_orders(strategy, signal_data)

        except Exception as e:
            logger.error(f"Error executing strategy {strategy.id}: {str(e)}")
            strategy.failed_trades += 1
            self.db.commit()
            raise

    async def _execute_single_account_strategy(
        self,
        strategy: ActivatedStrategy,
        signal_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a single account trading strategy with enhanced error handling"""
        
        circuit_name = f"strategy_{strategy.id}"
        
        with logging_context(
            strategy_id=strategy.id,
            account_id=strategy.account_id,
            ticker=strategy.ticker,
            action=signal_data.get("action")
        ):
            async with shutdown_manager.track_task(
                "strategy_execution",
                f"strategy_{strategy.id}_{strategy.account_id}",
                strategy_id=strategy.id,
                account_id=strategy.account_id
            ):
                # Use circuit breaker to prevent repeated failures
                try:
                    return await circuit_breaker_manager.execute_with_circuit_breaker(
                        circuit_name,
                        self._execute_strategy_with_rollback,
                        strategy,
                        signal_data
                    )
                except CircuitBreakerOpenError:
                    logger.warning(f"Circuit breaker open for strategy {strategy.id}",
                                 extra_context={"circuit_name": circuit_name})
                    return {
                        "status": "skipped",
                        "reason": "Circuit breaker is open - strategy temporarily disabled due to failures"
                    }
    
    async def _execute_strategy_with_rollback(
        self,
        strategy: ActivatedStrategy,
        signal_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute strategy with full rollback support"""
        
        # Use rollback manager for transaction safety
        async with rollback_manager.transaction_context(
            "strategy_execution",
            f"strategy_{strategy.id}_{int(time.time())}"
        ) as rollback_ctx:
            
            # Use account-level distributed locking to prevent race conditions
            async with AccountLockManager.lock_account(
                account_id=strategy.account_id,
                timeout=30.0,
                max_retries=3,
                operation_name=f"strategy_{strategy.id}_execution"
            ) as lock_acquired:
                
                if not lock_acquired:
                    logger.warning(f"Failed to acquire lock for account {strategy.account_id}",
                                 extra_context={"strategy_id": strategy.id})
                    return {
                        "status": "skipped",
                        "reason": "Could not acquire account lock - another strategy may be executing"
                    }
                
                # Use database transaction with automatic rollback
                async with rollback_ctx.database_transaction() as db:
                    
                    # Get account with validation
                    account = db.query(BrokerAccount).filter(
                        BrokerAccount.account_id == strategy.account_id,
                        BrokerAccount.is_active == True
                    ).first()

                    if not account:
                        raise HTTPException(status_code=404, detail="Trading account not found")

                    # Validate account credentials
                    if not account.credentials or not account.credentials.is_valid:
                        raise HTTPException(
                            status_code=401, 
                            detail="Invalid or expired account credentials"
                        )

                    # Get broker instance
                    broker = BaseBroker.get_broker_instance(account.broker_id, db)

                    # Ensure we have a valid contract ticker
                    valid, contract_ticker = validate_ticker(strategy.ticker)
                    if not valid:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Invalid ticker format: {strategy.ticker}"
                        )

                    # Check current positions to prevent duplicate trades
                    try:
                        positions = await broker.get_positions(account)
                        current_position = 0
                        for position in positions:
                            if position.get("symbol") == contract_ticker:
                                current_position = int(position.get("quantity", 0))
                                break
                        
                        logger.info(f"Current position for {contract_ticker}: {current_position}",
                                   operation="position_check",
                                   extra_context={"symbol": contract_ticker, "position": current_position})
                        
                        # Position-aware logic: check if we should execute based on current position
                        action = signal_data["action"].upper()
                        if action == "SELL" and current_position <= 0:
                            logger.info(f"Skipping SELL signal - no long position in {contract_ticker}",
                                       operation="position_validation")
                            return {
                                "status": "skipped", 
                                "reason": f"No long position to sell in {contract_ticker}"
                            }
                        elif action == "BUY" and current_position >= 0:
                            # Allow BUY signals to add to position or initiate new position
                            logger.info(f"Executing BUY signal for {contract_ticker}",
                                       operation="position_validation")
                            
                    except Exception as pos_error:
                        logger.warning(f"Could not check positions, proceeding with trade",
                                     operation="position_check", error=pos_error)

                    # Prepare and execute order with the validated contract ticker
                    order_data = {
                        "account_id": account.account_id,
                        "symbol": contract_ticker,  # Use the full contract ticker
                        "quantity": strategy.quantity,
                        "side": signal_data["action"],
                        "type": signal_data.get("order_type", "MARKET"),
                        "time_in_force": signal_data.get("time_in_force", "GTC"),
                    }

                    # Log the order details
                    logger.info(f"Executing order with distributed lock",
                               operation="order_execution",
                               extra_context={"order_data": order_data})

                    # Execute order
                    try:
                        order_result = await broker.place_order(account, order_data)
                        
                        # Add broker order cancellation to rollback if needed
                        if order_result.get("order_id"):
                            await rollback_ctx.add_broker_order_cancel(
                                broker, account, order_result["order_id"]
                            )
                        
                        # Log successful order execution
                        logger.log_trading_event(
                            "order_executed",
                            str(strategy.id),
                            strategy.account_id,
                            order_id=order_result.get("order_id"),
                            symbol=contract_ticker,
                            side=signal_data["action"],
                            quantity=strategy.quantity
                        )
                        
                    except Exception as order_error:
                        logger.exception(f"Order execution failed", 
                                       operation="order_execution", 
                                       error=order_error,
                                       extra_context={"order_data": order_data})
                        
                        # Send trading failure alert
                        await TradingAlerts.trading_failure(
                            strategy_id=str(strategy.id),
                            account_id=strategy.account_id,
                            error=str(order_error),
                            context={"order_data": order_data}
                        )
                        raise

                    # Update strategy statistics
                    await self._update_strategy_stats(strategy, order_result)
                    
                    # Add notification for successful execution
                    await rollback_ctx.add_notification(
                        f"Strategy {strategy.id} executed successfully on account {strategy.account_id}",
                        "trading_success"
                    )

                    return {
                        "status": "success",
                        "order_details": order_result,
                        "locked_execution": True,
                        "rollback_protected": True
                    }

    async def _execute_group_strategy(
        self,
        strategy: ActivatedStrategy,
        signal_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a group trading strategy involving a leader and multiple follower accounts.
        """
        results = []
        errors = []
        
        try:
            # Start a new transaction
            self.db.begin_nested()  # Create a savepoint
            
            logger.info(f"Starting group strategy execution for strategy {strategy.id}")
            
            # 1. Validate and get leader account
            leader_account = self.db.query(BrokerAccount).filter(
                BrokerAccount.account_id == strategy.leader_account_id,
                BrokerAccount.user_id == strategy.user_id,
                BrokerAccount.is_active == True
            ).first()

            if not leader_account:
                raise HTTPException(
                    status_code=404,
                    detail=f"Leader account {strategy.leader_account_id} not found or inactive"
                )

            # Validate the ticker
            valid, contract_ticker = validate_ticker(strategy.ticker)
            if not valid:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid ticker format: {strategy.ticker}"
                )
                
            # Update signal data with correct ticker format
            signal_data_copy = signal_data.copy()

            # 2. Execute leader order
            try:
                logger.info(f"Executing leader order for strategy {strategy.id}")
                
                # Create leader-specific strategy instance
                leader_strategy_dict = {
                    'user_id': strategy.user_id,
                    'strategy_type': 'single',
                    'webhook_id': strategy.webhook_id,
                    'ticker': contract_ticker,  # Use validated contract ticker
                    'account_id': strategy.leader_account_id,
                    'quantity': strategy.leader_quantity,
                    'is_active': strategy.is_active
                }
                
                leader_strategy = ActivatedStrategy(**leader_strategy_dict)
                leader_result = await self._execute_single_account_strategy(
                    leader_strategy,
                    signal_data_copy
                )
                
                results.append({
                    "account_type": "leader",
                    "account_id": strategy.leader_account_id,
                    "result": leader_result
                })

                # Update strategy statistics for leader
                if leader_result.get("status") == "success":
                    strategy.successful_trades = (strategy.successful_trades or 0) + 1
                    if "realized_pnl" in leader_result:
                        strategy.total_pnl = (strategy.total_pnl or Decimal('0')) + Decimal(str(leader_result["realized_pnl"]))
                else:
                    strategy.failed_trades = (strategy.failed_trades or 0) + 1

            except Exception as leader_error:
                logger.error(f"Leader order failed: {str(leader_error)}")
                self.db.rollback()  # Roll back to savepoint
                raise HTTPException(
                    status_code=500,
                    detail=f"Leader order failed: {str(leader_error)}"
                )

            # 3. Get follower accounts using the relationship
            follower_accounts = []
            for follower in strategy.follower_accounts_with_quantities:
                quantity = strategy.get_follower_quantity(follower.account_id)
                if quantity > 0:
                    follower_accounts.append({
                        "account": follower,
                        "quantity": quantity
                    })

            # 4. Execute follower orders
            for follower in follower_accounts:
                try:
                    follower_dict = {
                        'user_id': strategy.user_id,
                        'strategy_type': 'single',
                        'webhook_id': strategy.webhook_id,
                        'ticker': contract_ticker,  # Use validated contract ticker
                        'account_id': follower['account'].account_id,
                        'quantity': follower['quantity'],
                        'is_active': strategy.is_active
                    }

                    logger.info(f"Executing follower order for account {follower['account'].account_id}")
                    follower_strategy = ActivatedStrategy(**follower_dict)
                    follower_result = await self._execute_single_account_strategy(
                        follower_strategy,
                        signal_data_copy
                    )

                    results.append({
                        "account_type": "follower",
                        "account_id": follower['account'].account_id,
                        "result": follower_result
                    })

                    # Update strategy statistics for successful follower
                    if follower_result.get("status") == "success":
                        strategy.successful_trades = (strategy.successful_trades or 0) + 1
                        if "realized_pnl" in follower_result:
                            strategy.total_pnl = (strategy.total_pnl or Decimal('0')) + Decimal(str(follower_result["realized_pnl"]))
                    else:
                        strategy.failed_trades = (strategy.failed_trades or 0) + 1

                except Exception as follower_error:
                    error_msg = f"Follower order failed for account {follower['account'].account_id}: {str(follower_error)}"
                    logger.error(error_msg)
                    errors.append({
                        "account_type": "follower",
                        "account_id": follower['account'].account_id,
                        "error": error_msg
                    })

            # 5. Update overall strategy statistics
            try:
                strategy.total_trades = (strategy.total_trades or 0) + len(results)
                if strategy.total_trades > 0:
                    strategy.win_rate = Decimal(str((strategy.successful_trades or 0) / strategy.total_trades * 100))
                
                # Commit the transaction if everything succeeded
                self.db.commit()
                
                # 6. Prepare and return final result
                execution_status = "completed" if not errors else "completed_with_errors"
                
                return {
                    "status": execution_status,
                    "strategy_id": strategy.id,
                    "results": results,
                    "errors": errors,
                    "statistics": {
                        "total_trades": strategy.total_trades or 0,
                        "successful_trades": strategy.successful_trades or 0,
                        "failed_trades": strategy.failed_trades or 0,
                        "win_rate": float(strategy.win_rate) if strategy.win_rate else 0,
                        "total_pnl": float(strategy.total_pnl) if strategy.total_pnl else 0
                    },
                    "timestamp": datetime.utcnow().isoformat()
                }

            except Exception as stats_error:
                logger.error(f"Error updating strategy stats: {str(stats_error)}")
                self.db.rollback()
                raise HTTPException(
                    status_code=500,
                    detail=f"Error updating strategy statistics: {str(stats_error)}"
                )

        except HTTPException:
            raise
        except Exception as e:
            error_msg = f"Group strategy execution failed: {str(e)}"
            logger.error(f"{error_msg}\nTraceback: {traceback.format_exc()}")
            self.db.rollback()
            raise HTTPException(
                status_code=500,
                detail=error_msg,
                headers={"X-Error-Type": "group_strategy_error"}
            )

    async def _prepare_order_data(
        self,
        strategy: ActivatedStrategy,
        signal_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Prepare order data for execution"""
        # Validate and get the proper contract ticker
        valid, contract_ticker = validate_ticker(strategy.ticker)
        if not valid:
            raise ValueError(f"Invalid ticker format: {strategy.ticker}")
            
        return {
            "account_id": strategy.account_id,
            "symbol": contract_ticker,  # Use the validated contract ticker
            "quantity": strategy.quantity,
            "side": signal_data["action"],
            "type": signal_data.get("order_type", "MARKET"),
            "price": signal_data.get("price"),
            "stop_price": signal_data.get("stop_price"),
            "time_in_force": signal_data.get("time_in_force", "GTC"),
            "strategy_id": strategy.id
        }
    
    async def _get_account_status_with_retry(self, broker, account, max_retries=3):
        """Retry wrapper for getting account status"""
        for attempt in range(max_retries):
            try:
                return await broker.get_account_status(account)
            except Exception as e:
                logger.error(f"Account status fetch attempt {attempt + 1} failed: {str(e)}")
                if attempt == max_retries - 1:  # Last attempt
                    raise
                await asyncio.sleep(1 * (attempt + 1))  # Exponential backoff

    async def _execute_order_with_retry(self, broker, account, order_data, max_retries=3):
        """Retry wrapper for order execution"""
        for attempt in range(max_retries):
            try:
                return await broker.place_order(account, order_data)
            except Exception as e:
                logger.error(f"Order execution attempt {attempt + 1} failed: {str(e)}")
                if attempt == max_retries - 1:  # Last attempt
                    raise
                await asyncio.sleep(1 * (attempt + 1))

    async def _validate_risk_limits(
        self,
        strategy: ActivatedStrategy,
        account: BrokerAccount,
        order_data: Dict[str, Any]
    ) -> None:
        """Validate order against risk management rules"""
        try:
            # Get broker instance
            broker = BaseBroker.get_broker_instance(account.broker_id, self.db)

            # Get account positions
            positions = await broker.get_positions(account)
            
            # Check position size limits
            if strategy.max_position_size:
                current_position = sum(
                    abs(float(p["quantity"]))
                    for p in positions
                    if p["symbol"] == order_data["symbol"]  # Use the already validated symbol from order_data
                )
                if current_position + order_data["quantity"] > strategy.max_position_size:
                    raise HTTPException(
                        status_code=400,
                        detail="Order exceeds maximum position size"
                    )

            # Check account risk limits
            account_status = await broker.get_account_status(account)
            available_margin = Decimal(str(account_status.get("available_margin", 0)))
            
            if strategy.max_daily_loss:
                daily_pnl = Decimal(str(account_status.get("day_pnl", 0)))
                if abs(daily_pnl) > strategy.max_daily_loss:
                    raise HTTPException(
                        status_code=400,
                        detail="Daily loss limit exceeded"
                    )

        except HTTPException as he:
            raise he
        except Exception as e:
            logger.error(f"Error validating risk limits: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Risk validation failed: {str(e)}"
            )

    async def _update_strategy_stats(
        self,
        strategy: ActivatedStrategy,
        order_result: Dict[str, Any]
    ) -> None:
        """Update strategy statistics after order execution"""
        try:
            with logging_context(strategy_id=strategy.id, order_status=order_result.get("status")):
                strategy.total_trades += 1
                
                if order_result.get("status") == "filled":
                    strategy.successful_trades += 1
                    
                    # Calculate P&L if available
                    if "realized_pnl" in order_result:
                        pnl_value = Decimal(str(order_result["realized_pnl"]))
                        strategy.total_pnl += pnl_value
                        
                        logger.log_performance_metric(
                            "strategy_pnl",
                            float(pnl_value),
                            "USD",
                            strategy_id=strategy.id
                        )
                    
                    # Update other metrics
                    if strategy.total_trades > 0:
                        strategy.win_rate = (strategy.successful_trades / strategy.total_trades) * 100
                    
                    logger.info(f"Strategy stats updated - successful trade",
                               operation="stats_update",
                               extra_context={
                                   "total_trades": strategy.total_trades,
                                   "successful_trades": strategy.successful_trades,
                                   "win_rate": float(strategy.win_rate) if strategy.win_rate else 0
                               })
                    
                else:
                    strategy.failed_trades += 1
                    logger.warning(f"Strategy stats updated - failed trade",
                                 operation="stats_update",
                                 extra_context={
                                     "total_trades": strategy.total_trades,
                                     "failed_trades": strategy.failed_trades,
                                     "order_status": order_result.get("status")
                                 })

                self.db.commit()

        except Exception as e:
            logger.exception(f"Error updating strategy statistics", 
                           operation="stats_update", 
                           error=e,
                           extra_context={"strategy_id": strategy.id})
            # Don't raise here - stats update failure shouldn't fail the trade