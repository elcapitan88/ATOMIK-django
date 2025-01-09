from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
import logging
from datetime import datetime
from decimal import Decimal

from ..models.strategy import ActivatedStrategy
from ..models.broker import BrokerAccount, BrokerCredentials
from ..core.brokers.base import BaseBroker
from fastapi import HTTPException

logger = logging.getLogger(__name__)

class StrategyProcessor:
    def __init__(self, db: Session):
        self.db = db

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

            if strategy.strategy_type == 'single':
                return await self._execute_single_account_strategy(strategy, signal_data)
            else:
                return await self._execute_group_strategy(strategy, signal_data)

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
        """Execute strategy for a single account"""
        try:
            # Get account
            account = self.db.query(BrokerAccount).filter(
                BrokerAccount.account_id == strategy.account_id,
                BrokerAccount.is_active == True
            ).first()

            if not account:
                raise HTTPException(status_code=404, detail="Trading account not found")

            # Get broker instance
            broker = BaseBroker.get_broker_instance(account.broker_id, self.db)

            # Validate account status
            account_status = await broker.get_account_status(account)
            if account_status.get("status") != "active":
                raise HTTPException(
                    status_code=400,
                    detail=f"Account status is {account_status.get('status')}"
                )

            # Prepare order data
            order_data = await self._prepare_order_data(strategy, signal_data)

            # Check risk limits
            await self._validate_risk_limits(strategy, account, order_data)

            # Execute order through broker
            order_result = await broker.place_order(account, order_data)

            # Update strategy statistics
            await self._update_strategy_stats(strategy, order_result)

            return {
                "status": "success",
                "message": "Order executed successfully",
                "order_details": order_result
            }

        except HTTPException as he:
            raise he
        except Exception as e:
            logger.error(f"Error executing single account strategy: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Strategy execution failed: {str(e)}"
            )

    async def _execute_group_strategy(
        self,
        strategy: ActivatedStrategy,
        signal_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute strategy for a group of accounts"""
        results = []
        errors = []

        try:
            # Execute leader account first
            leader_account = self.db.query(BrokerAccount).filter(
                BrokerAccount.account_id == strategy.leader_account_id,
                BrokerAccount.is_active == True
            ).first()

            if not leader_account:
                raise HTTPException(
                    status_code=404,
                    detail="Leader account not found"
                )

            # Execute leader order
            leader_result = await self._execute_single_account_strategy(
                strategy,
                signal_data
            )
            results.append({"account": "leader", "result": leader_result})

            # Execute follower accounts
            for follower in strategy.follower_accounts:
                if not follower.is_active:
                    continue

                try:
                    # Create follower-specific strategy
                    follower_strategy = ActivatedStrategy(
                        **{
                            **strategy.__dict__,
                            'account_id': follower.account_id,
                            'quantity': strategy.follower_quantity
                        }
                    )

                    follower_result = await self._execute_single_account_strategy(
                        follower_strategy,
                        signal_data
                    )
                    results.append({
                        "account": follower.account_id,
                        "result": follower_result
                    })

                except Exception as e:
                    errors.append({
                        "account": follower.account_id,
                        "error": str(e)
                    })

            return {
                "status": "completed",
                "results": results,
                "errors": errors
            }

        except Exception as e:
            logger.error(f"Error executing group strategy: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Group strategy execution failed: {str(e)}"
            )

    async def _prepare_order_data(
        self,
        strategy: ActivatedStrategy,
        signal_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Prepare order data for execution"""
        return {
            "account_id": strategy.account_id,
            "symbol": strategy.ticker,
            "quantity": strategy.quantity,
            "side": signal_data["action"],
            "type": signal_data.get("order_type", "MARKET"),
            "price": signal_data.get("price"),
            "stop_price": signal_data.get("stop_price"),
            "time_in_force": signal_data.get("time_in_force", "GTC"),
            "strategy_id": strategy.id
        }

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
                    if p["symbol"] == strategy.ticker
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
            strategy.total_trades += 1
            
            if order_result.get("status") == "filled":
                strategy.successful_trades += 1
                
                # Calculate P&L if available
                if "realized_pnl" in order_result:
                    strategy.total_pnl += Decimal(str(order_result["realized_pnl"]))
                
                # Update other metrics
                if strategy.total_trades > 0:
                    strategy.win_rate = (strategy.successful_trades / strategy.total_trades) * 100
                
            else:
                strategy.failed_trades += 1

            self.db.commit()

        except Exception as e:
            logger.error(f"Error updating strategy stats: {str(e)}")
            # Don't raise here - stats update failure shouldn't fail the trade