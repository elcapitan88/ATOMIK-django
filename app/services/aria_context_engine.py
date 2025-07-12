# app/services/aria_context_engine.py
from typing import Dict, List, Optional, Any
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import json
import logging

from ..models.aria_context import UserTradingProfile, ARIAContextCache
from ..models.user import User
from ..models.strategy import ActivatedStrategy
from ..models.broker import BrokerAccount
from ..models.order import Order

logger = logging.getLogger(__name__)

class ARIAContextEngine:
    """
    Comprehensive user context engine for ARIA
    
    Provides rich context about user's trading activity, preferences, and patterns
    to enable intelligent ARIA responses and actions
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.cache_ttl_minutes = 15  # Cache context for 15 minutes
    
    async def get_user_context(self, user_id: int) -> Dict[str, Any]:
        """
        Get comprehensive user context for ARIA processing
        
        Returns rich context including:
        - Active positions and P&L
        - Strategy status and performance
        - Recent trading activity
        - User preferences and patterns
        - Market context
        """
        try:
            # Try to get from cache first
            cached_context = await self._get_cached_context(user_id)
            if cached_context:
                return cached_context
            
            # Build fresh context
            context = {
                "user_profile": await self._get_user_profile_context(user_id),
                "current_positions": await self._get_current_positions(user_id),
                "active_strategies": await self._get_active_strategies(user_id),
                "recent_trades": await self._get_recent_trades(user_id),
                "performance_summary": await self._get_performance_summary(user_id),
                "risk_metrics": await self._get_risk_metrics(user_id),
                "broker_status": await self._get_broker_status(user_id),
                "market_context": await self._get_market_context(),
                "preferences": await self._get_user_preferences(user_id),
                "trading_patterns": await self._get_trading_patterns(user_id)  # Future feature
            }
            
            # Cache the context
            await self._cache_context(user_id, context)
            
            return context
            
        except Exception as e:
            logger.error(f"Error getting user context for user {user_id}: {str(e)}")
            return self._get_minimal_context(user_id)
    
    async def update_context_cache(self, user_id: int) -> None:
        """Update cached context after significant events"""
        try:
            # Invalidate existing cache
            await self._invalidate_cache(user_id)
            
            # Rebuild context
            await self.get_user_context(user_id)
            
        except Exception as e:
            logger.error(f"Error updating context cache for user {user_id}: {str(e)}")
    
    async def _get_cached_context(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get context from cache if available and not expired"""
        try:
            cache_entry = self.db.query(ARIAContextCache).filter(
                ARIAContextCache.user_id == user_id,
                ARIAContextCache.cache_key == "full_context",
                ARIAContextCache.expires_at > datetime.utcnow()
            ).first()
            
            if cache_entry:
                # Update access stats
                cache_entry.cache_hit_count += 1
                cache_entry.last_accessed = datetime.utcnow()
                self.db.commit()
                
                return cache_entry.cache_data
            
            return None
            
        except Exception as e:
            logger.error(f"Error retrieving cached context: {str(e)}")
            return None
    
    async def _cache_context(self, user_id: int, context: Dict[str, Any]) -> None:
        """Cache user context for performance"""
        try:
            # Remove existing cache entry
            self.db.query(ARIAContextCache).filter(
                ARIAContextCache.user_id == user_id,
                ARIAContextCache.cache_key == "full_context"
            ).delete()
            
            # Create new cache entry
            cache_entry = ARIAContextCache(
                user_id=user_id,
                cache_key="full_context",
                cache_data=context,
                cache_timestamp=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(minutes=self.cache_ttl_minutes),
                data_source="context_engine",
                cache_hit_count=0,
                last_accessed=datetime.utcnow()
            )
            
            self.db.add(cache_entry)
            self.db.commit()
            
        except Exception as e:
            logger.error(f"Error caching context: {str(e)}")
    
    async def _invalidate_cache(self, user_id: int) -> None:
        """Invalidate cached context"""
        try:
            self.db.query(ARIAContextCache).filter(
                ARIAContextCache.user_id == user_id
            ).delete()
            self.db.commit()
            
        except Exception as e:
            logger.error(f"Error invalidating cache: {str(e)}")
    
    async def _get_user_profile_context(self, user_id: int) -> Dict[str, Any]:
        """Get user profile and trading characteristics"""
        try:
            user = self.db.query(User).filter(User.id == user_id).first()
            profile = self.db.query(UserTradingProfile).filter(
                UserTradingProfile.user_id == user_id
            ).first()
            
            if not user:
                return {}
            
            context = {
                "user_id": user_id,
                "username": user.username,
                "full_name": user.full_name,
                "account_created": user.created_at.isoformat() if user.created_at else None,
                "app_role": user.app_role
            }
            
            if profile:
                context.update({
                    "total_trades": profile.total_trades or 0,
                    "win_rate": profile.win_rate or 0.0,
                    "avg_hold_time_minutes": profile.avg_hold_time,
                    "risk_tolerance": profile.risk_tolerance,
                    "preferred_timeframes": profile.preferred_timeframes or [],
                    "preferred_instruments": profile.preferred_instruments or [],
                    "preferred_brokers": profile.preferred_brokers or [],
                    "max_position_size": profile.max_position_size
                })
            
            return context
            
        except Exception as e:
            logger.error(f"Error getting user profile context: {str(e)}")
            return {"user_id": user_id}
    
    async def _get_current_positions(self, user_id: int) -> Dict[str, Any]:
        """Get current trading positions across all brokers"""
        try:
            # This would integrate with actual broker APIs
            # For now, return mock data structure
            
            positions = {
                "AAPL": {
                    "symbol": "AAPL",
                    "quantity": 100,
                    "avg_price": 150.25,
                    "current_price": 152.30,
                    "unrealized_pnl": 205.00,
                    "unrealized_pnl_percent": 1.36,
                    "broker": "interactive_brokers",
                    "position_type": "long",
                    "entry_time": "2025-01-12T09:30:00Z"
                },
                "TSLA": {
                    "symbol": "TSLA",
                    "quantity": -50,
                    "avg_price": 245.80,
                    "current_price": 242.50,
                    "unrealized_pnl": 165.00,
                    "unrealized_pnl_percent": 1.34,
                    "broker": "interactive_brokers", 
                    "position_type": "short",
                    "entry_time": "2025-01-12T10:15:00Z"
                }
            }
            
            # Calculate totals
            total_unrealized_pnl = sum(pos["unrealized_pnl"] for pos in positions.values())
            total_positions = len(positions)
            
            return {
                "positions": positions,
                "total_positions": total_positions,
                "total_unrealized_pnl": total_unrealized_pnl,
                "last_updated": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting current positions: {str(e)}")
            return {"positions": {}, "total_positions": 0, "total_unrealized_pnl": 0.0}
    
    async def _get_active_strategies(self, user_id: int) -> List[Dict[str, Any]]:
        """Get currently active trading strategies"""
        try:
            strategies = self.db.query(ActivatedStrategy).filter(
                ActivatedStrategy.user_id == user_id,
                ActivatedStrategy.is_active == True
            ).all()
            
            strategy_list = []
            for strategy in strategies:
                strategy_list.append({
                    "id": strategy.id,
                    "name": strategy.name,
                    "description": strategy.description or "",
                    "is_active": strategy.is_active,
                    "broker": strategy.broker,
                    "created_at": strategy.created_at.isoformat() if strategy.created_at else None,
                    "last_updated": strategy.updated_at.isoformat() if strategy.updated_at else None,
                    # Add performance metrics (would come from strategy execution tracking)
                    "trades_today": 0,  # Placeholder
                    "daily_pnl": 0.0,   # Placeholder
                    "win_rate": 0.0     # Placeholder
                })
            
            return strategy_list
            
        except Exception as e:
            logger.error(f"Error getting active strategies: {str(e)}")
            return []
    
    async def _get_recent_trades(self, user_id: int, days: int = 7) -> List[Dict[str, Any]]:
        """Get recent trading activity"""
        try:
            start_date = datetime.utcnow() - timedelta(days=days)
            
            orders = self.db.query(Order).filter(
                Order.user_id == user_id,
                Order.created_at >= start_date
            ).order_by(Order.created_at.desc()).limit(50).all()
            
            trades = []
            for order in orders:
                trades.append({
                    "id": order.id,
                    "symbol": order.symbol,
                    "side": order.side,
                    "quantity": order.quantity,
                    "price": order.price,
                    "status": order.status,
                    "broker": order.broker,
                    "timestamp": order.created_at.isoformat() if order.created_at else None,
                    "strategy_id": order.strategy_id,
                    # Calculate P&L if filled
                    "pnl": 0.0  # Would calculate from fills
                })
            
            return trades
            
        except Exception as e:
            logger.error(f"Error getting recent trades: {str(e)}")
            return []
    
    async def _get_performance_summary(self, user_id: int) -> Dict[str, Any]:
        """Get performance summary for different time periods"""
        try:
            # This would integrate with actual trade tracking
            # For now, return mock performance data
            
            today = datetime.utcnow().date()
            
            return {
                "daily_pnl": 250.75,
                "daily_trades": 8,
                "daily_win_rate": 0.625,
                "weekly_pnl": 1125.30,
                "weekly_trades": 42,
                "monthly_pnl": 4560.80,
                "monthly_trades": 187,
                "total_account_value": 125000.00,
                "available_buying_power": 45000.00,
                "largest_winner_today": 125.50,
                "largest_loser_today": -85.25,
                "current_drawdown": -150.00,
                "max_drawdown_this_month": -890.00,
                "sharpe_ratio": 1.42,
                "profit_factor": 1.35,
                "last_updated": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting performance summary: {str(e)}")
            return {
                "daily_pnl": 0.0,
                "daily_trades": 0,
                "total_account_value": 0.0
            }
    
    async def _get_risk_metrics(self, user_id: int) -> Dict[str, Any]:
        """Get current risk metrics and exposure"""
        try:
            return {
                "portfolio_beta": 1.15,
                "var_95": -1250.00,  # Value at Risk (95% confidence)
                "portfolio_volatility": 0.18,
                "correlation_with_spy": 0.85,
                "sector_exposure": {
                    "Technology": 35.5,
                    "Finance": 22.1,
                    "Healthcare": 15.8,
                    "Energy": 12.3,
                    "Consumer": 14.3
                },
                "max_single_position_risk": 5.2,  # % of portfolio
                "overnight_exposure": 65000.00,
                "margin_utilization": 0.32,
                "risk_score": 7.2,  # 1-10 scale
                "last_updated": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting risk metrics: {str(e)}")
            return {"risk_score": 5.0}
    
    async def _get_broker_status(self, user_id: int) -> Dict[str, Any]:
        """Get status of connected brokers"""
        try:
            broker_accounts = self.db.query(BrokerAccount).filter(
                BrokerAccount.user_id == user_id
            ).all()
            
            broker_status = {}
            for account in broker_accounts:
                broker_status[account.broker] = {
                    "connected": True,  # Would check actual API connection
                    "account_id": account.account_id,
                    "nickname": getattr(account, 'nickname', None),
                    "last_sync": datetime.utcnow().isoformat(),  # Would track actual sync
                    "trading_enabled": True,  # Would check account permissions
                    "market_data_connected": True
                }
            
            return broker_status
            
        except Exception as e:
            logger.error(f"Error getting broker status: {str(e)}")
            return {}
    
    async def _get_market_context(self) -> Dict[str, Any]:
        """Get current market context for intelligent responses"""
        try:
            # This would integrate with market data APIs
            # For now, return mock market context
            
            return {
                "market_status": "open",  # open, closed, pre_market, after_hours
                "spy_price": 485.25,
                "spy_change": 1.85,
                "spy_change_percent": 0.38,
                "vix": 18.45,
                "vix_change": -1.25,
                "market_sentiment": "bullish",  # bullish, bearish, neutral
                "volume_vs_avg": 1.15,  # Higher than average
                "sector_leaders": ["Technology", "Healthcare"],
                "sector_laggards": ["Energy", "Utilities"],
                "earnings_today": ["AAPL", "MSFT", "GOOGL"],
                "economic_events": [
                    {"time": "08:30", "event": "Initial Jobless Claims", "importance": "medium"},
                    {"time": "10:00", "event": "Consumer Sentiment", "importance": "high"}
                ],
                "last_updated": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting market context: {str(e)}")
            return {"market_status": "unknown"}
    
    async def _get_user_preferences(self, user_id: int) -> Dict[str, Any]:
        """Get user preferences for ARIA responses"""
        try:
            profile = self.db.query(UserTradingProfile).filter(
                UserTradingProfile.user_id == user_id
            ).first()
            
            preferences = {
                "response_style": "professional",  # professional, casual, detailed
                "notification_level": "important",  # all, important, critical
                "voice_enabled": True,
                "auto_confirm_low_risk": False,
                "preferred_currency": "USD",
                "timezone": "America/New_York",
                "trading_hours_only": True
            }
            
            if profile:
                preferences.update({
                    "risk_tolerance": profile.risk_tolerance,
                    "max_position_size": profile.max_position_size,
                    "preferred_brokers": profile.preferred_brokers or [],
                    "preferred_timeframes": profile.preferred_timeframes or []
                })
            
            return preferences
            
        except Exception as e:
            logger.error(f"Error getting user preferences: {str(e)}")
            return {"response_style": "professional"}
    
    async def _get_trading_patterns(self, user_id: int) -> Dict[str, Any]:
        """Get user trading patterns for advanced insights (Future feature)"""
        try:
            # This would analyze historical trading data for patterns
            # Currently returns placeholder data - implement with ML analysis
            
            return {
                "best_trading_hours": [9, 10, 11],  # Hours of day (EST)
                "worst_trading_days": [2, 4],  # Tuesday, Thursday (0=Monday)
                "performance_by_day": {
                    "Monday": {"avg_pnl": 125.50, "win_rate": 0.68, "trades": 45},
                    "Tuesday": {"avg_pnl": -89.20, "win_rate": 0.42, "trades": 38},
                    "Wednesday": {"avg_pnl": 67.80, "win_rate": 0.58, "trades": 41},
                    "Thursday": {"avg_pnl": -45.30, "win_rate": 0.45, "trades": 35},
                    "Friday": {"avg_pnl": 98.40, "win_rate": 0.62, "trades": 29}
                },
                "optimal_position_size": 250,  # Shares
                "revenge_trading_risk": 0.25,  # 0-1 score
                "overtrading_tendency": 0.35,  # 0-1 score
                "best_market_conditions": ["low_volatility", "uptrend"],
                "pattern_confidence": 0.75,  # How reliable these patterns are
                "last_analysis": "2025-01-10T00:00:00Z"
            }
            
        except Exception as e:
            logger.error(f"Error getting trading patterns: {str(e)}")
            return {"pattern_confidence": 0.0}
    
    def _get_minimal_context(self, user_id: int) -> Dict[str, Any]:
        """Get minimal context when full context fails"""
        return {
            "user_profile": {"user_id": user_id},
            "current_positions": {"positions": {}, "total_positions": 0},
            "active_strategies": [],
            "recent_trades": [],
            "performance_summary": {"daily_pnl": 0.0, "daily_trades": 0},
            "risk_metrics": {"risk_score": 5.0},
            "broker_status": {},
            "market_context": {"market_status": "unknown"},
            "preferences": {"response_style": "professional"},
            "trading_patterns": {"pattern_confidence": 0.0}
        }