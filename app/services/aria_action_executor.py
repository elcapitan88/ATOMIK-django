# app/services/aria_action_executor.py
from typing import Dict, List, Optional, Any
from sqlalchemy.orm import Session
from datetime import datetime
import logging
from enum import Enum

from ..models.strategy import ActivatedStrategy
from ..models.broker import BrokerAccount
from ..models.order import Order
from .intent_service import VoiceIntent

logger = logging.getLogger(__name__)

class ActionType(Enum):
    """Types of actions ARIA can execute"""
    STRATEGY_CONTROL = "strategy_control"
    TRADE_EXECUTION = "trade_execution"
    POSITION_QUERY = "position_query"
    ACCOUNT_CONTROL = "account_control"
    RISK_MANAGEMENT = "risk_management"

class ActionResult:
    """Standardized action result"""
    def __init__(self, success: bool, action_type: str, message: str, data: Dict[str, Any] = None, error: str = None):
        self.success = success
        self.action_type = action_type
        self.message = message
        self.data = data or {}
        self.error = error
        self.timestamp = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "action_type": self.action_type,
            "message": self.message,
            "data": self.data,
            "error": self.error,
            "timestamp": self.timestamp.isoformat()
        }

class ARIAActionExecutor:
    """
    Action execution engine for ARIA commands
    
    Safely executes user commands with proper validation and error handling
    """
    
    def __init__(self, db: Session):
        self.db = db
    
    async def execute_action(
        self, 
        user_id: int, 
        intent: VoiceIntent, 
        user_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute action based on parsed intent
        
        Args:
            user_id: User's database ID
            intent: Parsed voice intent with parameters
            user_context: Full user context for validation
            
        Returns:
            Action result with success status and details
        """
        try:
            logger.info(f"Executing action for user {user_id}: {intent.type} with params {intent.parameters}")
            
            # Route to appropriate action handler
            if intent.type == ActionType.STRATEGY_CONTROL.value:
                result = await self._execute_strategy_control(user_id, intent, user_context)
            
            elif intent.type == ActionType.TRADE_EXECUTION.value:
                result = await self._execute_trade(user_id, intent, user_context)
            
            elif intent.type == ActionType.POSITION_QUERY.value:
                result = await self._execute_position_query(user_id, intent, user_context)
            
            elif intent.type == ActionType.ACCOUNT_CONTROL.value:
                result = await self._execute_account_control(user_id, intent, user_context)
            
            else:
                result = ActionResult(
                    success=False,
                    action_type=intent.type,
                    message=f"Action type '{intent.type}' not supported",
                    error="Unsupported action type"
                )
            
            return result.to_dict()
            
        except Exception as e:
            logger.error(f"Error executing action for user {user_id}: {str(e)}")
            
            error_result = ActionResult(
                success=False,
                action_type=intent.type,
                message="Action execution failed",
                error=str(e)
            )
            
            return error_result.to_dict()
    
    async def _execute_strategy_control(
        self, 
        user_id: int, 
        intent: VoiceIntent, 
        user_context: Dict[str, Any]
    ) -> ActionResult:
        """Execute strategy control commands"""
        try:
            strategy_name = intent.parameters.get("strategy_name")
            action = intent.parameters.get("action", "").lower()
            
            if not strategy_name and not action:
                return ActionResult(
                    success=False,
                    action_type="strategy_control",
                    message="Strategy name or action is required",
                    error="Missing required parameters"
                )
            
            # Handle bulk actions (all strategies)
            if action in ["start", "stop", "pause", "resume"] and not strategy_name:
                return await self._handle_bulk_strategy_action(user_id, action)
            
            # Handle specific strategy
            if strategy_name:
                return await self._handle_specific_strategy_action(user_id, strategy_name, action)
            
            return ActionResult(
                success=False,
                action_type="strategy_control",
                message="Invalid strategy control parameters",
                error="Cannot determine strategy or action"
            )
            
        except Exception as e:
            logger.error(f"Strategy control error: {str(e)}")
            return ActionResult(
                success=False,
                action_type="strategy_control",
                message="Strategy control failed",
                error=str(e)
            )
    
    async def _handle_specific_strategy_action(
        self, 
        user_id: int, 
        strategy_name: str, 
        action: str
    ) -> ActionResult:
        """Handle action on a specific strategy"""
        try:
            # Find strategy by name (fuzzy matching)
            strategies = self.db.query(ActivatedStrategy).filter(
                ActivatedStrategy.user_id == user_id
            ).all()
            
            # Find best match for strategy name
            target_strategy = None
            for strategy in strategies:
                if strategy_name.lower() in strategy.name.lower() or strategy.name.lower() in strategy_name.lower():
                    target_strategy = strategy
                    break
            
            if not target_strategy:
                return ActionResult(
                    success=False,
                    action_type="strategy_control",
                    message=f"Strategy '{strategy_name}' not found",
                    error="Strategy not found",
                    data={"available_strategies": [s.name for s in strategies]}
                )
            
            # Execute action
            if action in ["activate", "start", "enable", "turn on"]:
                target_strategy.is_active = True
                action_desc = "activated"
            elif action in ["deactivate", "stop", "disable", "turn off"]:
                target_strategy.is_active = False
                action_desc = "deactivated"
            else:
                return ActionResult(
                    success=False,
                    action_type="strategy_control",
                    message=f"Unknown action '{action}' for strategy control",
                    error="Invalid action"
                )
            
            target_strategy.updated_at = datetime.utcnow()
            self.db.commit()
            
            return ActionResult(
                success=True,
                action_type="strategy_control",
                message=f"Strategy '{target_strategy.name}' has been {action_desc}",
                data={
                    "strategy_id": target_strategy.id,
                    "strategy_name": target_strategy.name,
                    "action": action_desc,
                    "is_active": target_strategy.is_active,
                    "broker": target_strategy.broker
                }
            )
            
        except Exception as e:
            logger.error(f"Specific strategy action error: {str(e)}")
            return ActionResult(
                success=False,
                action_type="strategy_control",
                message="Failed to control strategy",
                error=str(e)
            )
    
    async def _handle_bulk_strategy_action(
        self, 
        user_id: int, 
        action: str
    ) -> ActionResult:
        """Handle bulk actions on all strategies"""
        try:
            strategies = self.db.query(ActivatedStrategy).filter(
                ActivatedStrategy.user_id == user_id
            ).all()
            
            if not strategies:
                return ActionResult(
                    success=False,
                    action_type="strategy_control",
                    message="No strategies found to control",
                    error="No strategies available"
                )
            
            # Determine new state
            if action in ["start", "resume"]:
                new_state = True
                action_desc = "activated"
            elif action in ["stop", "pause"]:
                new_state = False
                action_desc = "deactivated"
            else:
                return ActionResult(
                    success=False,
                    action_type="strategy_control",
                    message=f"Unknown bulk action '{action}'",
                    error="Invalid bulk action"
                )
            
            # Update all strategies
            affected_strategies = []
            for strategy in strategies:
                if strategy.is_active != new_state:  # Only change if different
                    strategy.is_active = new_state
                    strategy.updated_at = datetime.utcnow()
                    affected_strategies.append({
                        "id": strategy.id,
                        "name": strategy.name,
                        "broker": strategy.broker
                    })
            
            self.db.commit()
            
            return ActionResult(
                success=True,
                action_type="strategy_control",
                message=f"{len(affected_strategies)} strategies have been {action_desc}",
                data={
                    "action": action_desc,
                    "affected_count": len(affected_strategies),
                    "total_strategies": len(strategies),
                    "affected_strategies": affected_strategies
                }
            )
            
        except Exception as e:
            logger.error(f"Bulk strategy action error: {str(e)}")
            return ActionResult(
                success=False,
                action_type="strategy_control",
                message="Failed to control strategies",
                error=str(e)
            )
    
    async def _execute_trade(
        self, 
        user_id: int, 
        intent: VoiceIntent, 
        user_context: Dict[str, Any]
    ) -> ActionResult:
        """Execute trade orders"""
        try:
            symbol = intent.parameters.get("symbol", "").upper()
            action = intent.parameters.get("action", "").lower()
            quantity = intent.parameters.get("quantity", 0)
            price = intent.parameters.get("price")
            
            if not symbol:
                return ActionResult(
                    success=False,
                    action_type="trade_execution",
                    message="Symbol is required for trade execution",
                    error="Missing symbol"
                )
            
            if not action:
                return ActionResult(
                    success=False,
                    action_type="trade_execution",
                    message="Trade action is required (buy, sell, close)",
                    error="Missing action"
                )
            
            # Handle position closing
            if action == "close":
                return await self._close_position(user_id, symbol, user_context)
            
            # Handle regular trades
            if action in ["buy", "sell", "short"] and not quantity:
                return ActionResult(
                    success=False,
                    action_type="trade_execution",
                    message="Quantity is required for buy/sell orders",
                    error="Missing quantity"
                )
            
            # Validate broker availability
            broker_status = user_context.get("broker_status", {})
            if not broker_status:
                return ActionResult(
                    success=False,
                    action_type="trade_execution",
                    message="No broker connections available",
                    error="No active brokers"
                )
            
            # For now, simulate trade execution
            # In production, this would integrate with actual broker APIs
            order_id = f"ARIA_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{symbol}"
            
            # Create order record
            order = Order(
                user_id=user_id,
                symbol=symbol,
                side=action,
                quantity=quantity,
                price=price,
                status="filled",  # Simulated fill
                broker="simulated",
                order_id=order_id,
                created_at=datetime.utcnow()
            )
            
            self.db.add(order)
            self.db.commit()
            
            return ActionResult(
                success=True,
                action_type="trade_execution",
                message=f"Trade executed: {action} {quantity} {symbol}",
                data={
                    "order_id": order_id,
                    "symbol": symbol,
                    "action": action,
                    "quantity": quantity,
                    "price": price or "market",
                    "status": "filled",
                    "broker": "simulated"
                }
            )
            
        except Exception as e:
            logger.error(f"Trade execution error: {str(e)}")
            return ActionResult(
                success=False,
                action_type="trade_execution",
                message="Trade execution failed",
                error=str(e)
            )
    
    async def _close_position(
        self, 
        user_id: int, 
        symbol: str, 
        user_context: Dict[str, Any]
    ) -> ActionResult:
        """Close an existing position"""
        try:
            positions = user_context.get("current_positions", {}).get("positions", {})
            
            if symbol not in positions:
                return ActionResult(
                    success=False,
                    action_type="trade_execution",
                    message=f"No open position found for {symbol}",
                    error="Position not found",
                    data={"available_symbols": list(positions.keys())}
                )
            
            position = positions[symbol]
            quantity = abs(position["quantity"])
            position_type = position["position_type"]
            
            # Determine closing action
            close_action = "sell" if position_type == "long" else "buy"
            
            # Simulate position close
            order_id = f"ARIA_CLOSE_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{symbol}"
            
            order = Order(
                user_id=user_id,
                symbol=symbol,
                side=close_action,
                quantity=quantity,
                status="filled",
                broker=position["broker"],
                order_id=order_id,
                created_at=datetime.utcnow()
            )
            
            self.db.add(order)
            self.db.commit()
            
            return ActionResult(
                success=True,
                action_type="trade_execution",
                message=f"Closed {symbol} position: {close_action} {quantity} shares",
                data={
                    "order_id": order_id,
                    "symbol": symbol,
                    "action": "close",
                    "close_action": close_action,
                    "quantity": quantity,
                    "original_position_type": position_type,
                    "unrealized_pnl": position["unrealized_pnl"],
                    "broker": position["broker"]
                }
            )
            
        except Exception as e:
            logger.error(f"Position close error: {str(e)}")
            return ActionResult(
                success=False,
                action_type="trade_execution",
                message="Failed to close position",
                error=str(e)
            )
    
    async def _execute_position_query(
        self, 
        user_id: int, 
        intent: VoiceIntent, 
        user_context: Dict[str, Any]
    ) -> ActionResult:
        """Execute position queries"""
        try:
            symbol = intent.parameters.get("symbol", "").upper()
            positions = user_context.get("current_positions", {}).get("positions", {})
            
            if symbol:
                # Specific symbol query
                if symbol in positions:
                    position = positions[symbol]
                    return ActionResult(
                        success=True,
                        action_type="position_query",
                        message=f"{symbol} position: {position['quantity']} shares, P&L: ${position['unrealized_pnl']:.2f}",
                        data=position
                    )
                else:
                    return ActionResult(
                        success=True,
                        action_type="position_query",
                        message=f"No {symbol} position found",
                        data={"symbol": symbol, "position": None}
                    )
            else:
                # All positions query
                total_positions = len(positions)
                total_pnl = sum(pos["unrealized_pnl"] for pos in positions.values())
                
                return ActionResult(
                    success=True,
                    action_type="position_query",
                    message=f"You have {total_positions} positions with total unrealized P&L of ${total_pnl:.2f}",
                    data={
                        "total_positions": total_positions,
                        "total_unrealized_pnl": total_pnl,
                        "positions": positions
                    }
                )
                
        except Exception as e:
            logger.error(f"Position query error: {str(e)}")
            return ActionResult(
                success=False,
                action_type="position_query",
                message="Failed to retrieve position information",
                error=str(e)
            )
    
    async def _execute_account_control(
        self, 
        user_id: int, 
        intent: VoiceIntent, 
        user_context: Dict[str, Any]
    ) -> ActionResult:
        """Execute high-risk account control actions"""
        try:
            action = intent.parameters.get("action", "").lower()
            
            if "close all" in action or "liquidate" in action:
                return await self._close_all_positions(user_id, user_context)
            
            elif "stop all" in action or "emergency" in action:
                return await self._emergency_stop(user_id, user_context)
            
            elif "disable all" in action:
                return await self._disable_all_strategies(user_id)
            
            else:
                return ActionResult(
                    success=False,
                    action_type="account_control",
                    message=f"Unknown account control action: {action}",
                    error="Invalid account action"
                )
                
        except Exception as e:
            logger.error(f"Account control error: {str(e)}")
            return ActionResult(
                success=False,
                action_type="account_control",
                message="Account control action failed",
                error=str(e)
            )
    
    async def _close_all_positions(
        self, 
        user_id: int, 
        user_context: Dict[str, Any]
    ) -> ActionResult:
        """Close all open positions"""
        try:
            positions = user_context.get("current_positions", {}).get("positions", {})
            
            if not positions:
                return ActionResult(
                    success=True,
                    action_type="account_control",
                    message="No open positions to close",
                    data={"positions_closed": 0}
                )
            
            closed_positions = []
            for symbol, position in positions.items():
                # Simulate closing each position
                quantity = abs(position["quantity"])
                close_action = "sell" if position["position_type"] == "long" else "buy"
                
                order_id = f"ARIA_CLOSEALL_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{symbol}"
                
                order = Order(
                    user_id=user_id,
                    symbol=symbol,
                    side=close_action,
                    quantity=quantity,
                    status="filled",
                    broker=position["broker"],
                    order_id=order_id,
                    created_at=datetime.utcnow()
                )
                
                self.db.add(order)
                closed_positions.append({
                    "symbol": symbol,
                    "quantity": quantity,
                    "action": close_action,
                    "pnl": position["unrealized_pnl"]
                })
            
            self.db.commit()
            
            total_pnl = sum(pos["pnl"] for pos in closed_positions)
            
            return ActionResult(
                success=True,
                action_type="account_control",
                message=f"Closed all {len(closed_positions)} positions. Total realized P&L: ${total_pnl:.2f}",
                data={
                    "positions_closed": len(closed_positions),
                    "total_realized_pnl": total_pnl,
                    "closed_positions": closed_positions
                }
            )
            
        except Exception as e:
            logger.error(f"Close all positions error: {str(e)}")
            return ActionResult(
                success=False,
                action_type="account_control",
                message="Failed to close all positions",
                error=str(e)
            )
    
    async def _emergency_stop(
        self, 
        user_id: int, 
        user_context: Dict[str, Any]
    ) -> ActionResult:
        """Emergency stop - disable strategies and close positions"""
        try:
            # Disable all strategies
            strategies = self.db.query(ActivatedStrategy).filter(
                ActivatedStrategy.user_id == user_id,
                ActivatedStrategy.is_active == True
            ).all()
            
            strategies_disabled = 0
            for strategy in strategies:
                strategy.is_active = False
                strategy.updated_at = datetime.utcnow()
                strategies_disabled += 1
            
            # Close all positions (reuse existing method)
            close_result = await self._close_all_positions(user_id, user_context)
            
            self.db.commit()
            
            return ActionResult(
                success=True,
                action_type="account_control",
                message=f"Emergency stop executed: {strategies_disabled} strategies disabled, {close_result.data.get('positions_closed', 0)} positions closed",
                data={
                    "strategies_disabled": strategies_disabled,
                    "positions_closed": close_result.data.get("positions_closed", 0),
                    "total_realized_pnl": close_result.data.get("total_realized_pnl", 0)
                }
            )
            
        except Exception as e:
            logger.error(f"Emergency stop error: {str(e)}")
            return ActionResult(
                success=False,
                action_type="account_control",
                message="Emergency stop failed",
                error=str(e)
            )
    
    async def _disable_all_strategies(self, user_id: int) -> ActionResult:
        """Disable all active strategies"""
        try:
            strategies = self.db.query(ActivatedStrategy).filter(
                ActivatedStrategy.user_id == user_id,
                ActivatedStrategy.is_active == True
            ).all()
            
            if not strategies:
                return ActionResult(
                    success=True,
                    action_type="account_control",
                    message="No active strategies to disable",
                    data={"strategies_disabled": 0}
                )
            
            strategy_names = []
            for strategy in strategies:
                strategy.is_active = False
                strategy.updated_at = datetime.utcnow()
                strategy_names.append(strategy.name)
            
            self.db.commit()
            
            return ActionResult(
                success=True,
                action_type="account_control",
                message=f"Disabled {len(strategies)} strategies: {', '.join(strategy_names[:3])}{'...' if len(strategy_names) > 3 else ''}",
                data={
                    "strategies_disabled": len(strategies),
                    "strategy_names": strategy_names
                }
            )
            
        except Exception as e:
            logger.error(f"Disable all strategies error: {str(e)}")
            return ActionResult(
                success=False,
                action_type="account_control",
                message="Failed to disable strategies",
                error=str(e)
            )