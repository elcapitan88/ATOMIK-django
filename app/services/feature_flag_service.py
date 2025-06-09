"""
Feature Flag Service for Dynamic Beta Feature Management

This service provides dynamic feature flag capabilities for the beta testing system,
allowing real-time control over feature availability, gradual rollouts, and A/B testing.
"""

import logging
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, asdict
import json
from sqlalchemy.orm import Session
from app.services.chat_role_service import is_user_admin, is_user_moderator, is_user_beta_tester

logger = logging.getLogger(__name__)


class FeatureStatus(Enum):
    """Feature flag status options"""
    DISABLED = "disabled"
    BETA = "beta"
    ENABLED = "enabled"
    DEPRECATED = "deprecated"
    

class RolloutStrategy(Enum):
    """Feature rollout strategies"""
    ALL_USERS = "all_users"
    PERCENTAGE = "percentage"
    USER_LIST = "user_list"
    ROLE_BASED = "role_based"
    GRADUAL = "gradual"


@dataclass
class FeatureConfig:
    """Feature flag configuration"""
    name: str
    status: FeatureStatus
    rollout_strategy: RolloutStrategy
    rollout_percentage: int = 0
    target_users: List[int] = None
    target_roles: List[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    description: str = ""
    dependencies: List[str] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.target_users is None:
            self.target_users = []
        if self.target_roles is None:
            self.target_roles = []
        if self.dependencies is None:
            self.dependencies = []
        if self.metadata is None:
            self.metadata = {}


class FeatureFlagService:
    """Service for managing feature flags and beta feature access"""
    
    def __init__(self, db: Session):
        self.db = db
        self._feature_configs = self._load_feature_configs()
    
    def _load_feature_configs(self) -> Dict[str, FeatureConfig]:
        """Load feature configurations from database or config file"""
        # For now, we'll use in-memory configuration
        # In production, this would load from database or Redis
        return {
            "advanced-analytics": FeatureConfig(
                name="advanced-analytics",
                status=FeatureStatus.BETA,
                rollout_strategy=RolloutStrategy.ROLE_BASED,
                target_roles=["Beta Tester", "Admin", "Moderator"],
                description="Enhanced analytics dashboard with predictive insights",
                dependencies=["basic-analytics"],
                metadata={"category": "Advanced Analytics", "priority": "high"}
            ),
            "new-dashboard": FeatureConfig(
                name="new-dashboard",
                status=FeatureStatus.BETA,
                rollout_strategy=RolloutStrategy.PERCENTAGE,
                rollout_percentage=25,
                description="Redesigned user dashboard with improved UX",
                metadata={"category": "UI Enhancements", "priority": "medium"}
            ),
            "experimental-trading": FeatureConfig(
                name="experimental-trading",
                status=FeatureStatus.BETA,
                rollout_strategy=RolloutStrategy.ROLE_BASED,
                target_roles=["Beta Tester", "Admin"],
                description="Advanced trading algorithms and order types",
                dependencies=["basic-trading"],
                metadata={"category": "Trading Features", "priority": "high"}
            ),
            "ai-insights": FeatureConfig(
                name="ai-insights",
                status=FeatureStatus.BETA,
                rollout_strategy=RolloutStrategy.GRADUAL,
                rollout_percentage=10,
                start_date=datetime.now(),
                end_date=datetime.now() + timedelta(days=30),
                description="AI-powered trading insights and recommendations",
                dependencies=["advanced-analytics"],
                metadata={"category": "App Features", "priority": "high"}
            ),
            "advanced-charts": FeatureConfig(
                name="advanced-charts",
                status=FeatureStatus.ENABLED,
                rollout_strategy=RolloutStrategy.ALL_USERS,
                description="Enhanced charting capabilities with custom indicators",
                metadata={"category": "UI Enhancements", "priority": "medium"}
            ),
            "broker-integration-v2": FeatureConfig(
                name="broker-integration-v2",
                status=FeatureStatus.BETA,
                rollout_strategy=RolloutStrategy.USER_LIST,
                target_users=[],  # Will be populated by admin
                description="Next-generation broker integration with improved reliability",
                dependencies=["basic-broker-integration"],
                metadata={"category": "Integrations", "priority": "high"}
            ),
            "social-trading": FeatureConfig(
                name="social-trading",
                status=FeatureStatus.DISABLED,
                rollout_strategy=RolloutStrategy.ROLE_BASED,
                target_roles=["Beta Tester"],
                description="Social trading features and copy trading",
                metadata={"category": "App Features", "priority": "low"}
            ),
            "mobile-app-preview": FeatureConfig(
                name="mobile-app-preview",
                status=FeatureStatus.BETA,
                rollout_strategy=RolloutStrategy.PERCENTAGE,
                rollout_percentage=5,
                description="Preview of upcoming mobile application features",
                metadata={"category": "App Features", "priority": "medium"}
            ),
            "member-chat": FeatureConfig(
                name="member-chat",
                status=FeatureStatus.BETA,
                rollout_strategy=RolloutStrategy.ROLE_BASED,
                target_roles=["Admin", "Beta Tester"],
                description="Real-time member chat system for community interaction",
                metadata={"category": "Communication", "priority": "high"}
            ),
            "strategy-builder": FeatureConfig(
                name="strategy-builder",
                status=FeatureStatus.BETA,
                rollout_strategy=RolloutStrategy.ROLE_BASED,
                target_roles=["Admin", "Beta Tester"],
                description="Advanced strategy builder with drag-drop interface and AI integration",
                metadata={"category": "Trading Features", "priority": "high"}
            ),
            "atomik-trading-lab": FeatureConfig(
                name="atomik-trading-lab",
                status=FeatureStatus.BETA,
                rollout_strategy=RolloutStrategy.PERCENTAGE,
                rollout_percentage=5,  # Start with 5% of new users
                description="Premium onboarding flow and Trading Lab dashboard with network synchronization",
                dependencies=[],
                metadata={"category": "UI Enhancements", "priority": "high"}
            )
        }
    
    async def is_feature_enabled(self, feature_name: str, user_id: int) -> bool:
        """
        Check if a feature is enabled for a specific user
        
        Args:
            feature_name: Name of the feature to check
            user_id: ID of the user
            
        Returns:
            bool: True if feature is enabled for user
        """
        try:
            logger.info(f"Checking feature '{feature_name}' for user {user_id}")
            config = self._feature_configs.get(feature_name)
            if not config:
                logger.warning(f"Feature config not found: {feature_name}")
                return False
            
            logger.info(f"Feature {feature_name} config: status={config.status}, strategy={config.rollout_strategy}, target_roles={config.target_roles}")
            
            # Check if feature is globally disabled
            if config.status == FeatureStatus.DISABLED:
                logger.info(f"Feature {feature_name} is globally disabled")
                return False
            
            # Check if feature is globally enabled
            if config.status == FeatureStatus.ENABLED and config.rollout_strategy == RolloutStrategy.ALL_USERS:
                logger.info(f"Feature {feature_name} is globally enabled for all users")
                return True
            
            # Check date constraints
            now = datetime.now()
            if config.start_date and now < config.start_date:
                logger.info(f"Feature {feature_name} not yet available (start_date: {config.start_date})")
                return False
            if config.end_date and now > config.end_date:
                logger.info(f"Feature {feature_name} expired (end_date: {config.end_date})")
                return False
            
            # Check dependencies
            if config.dependencies:
                for dep in config.dependencies:
                    if not await self.is_feature_enabled(dep, user_id):
                        logger.debug(f"Feature {feature_name} disabled due to missing dependency: {dep}")
                        return False
            
            # Apply rollout strategy
            result = await self._check_rollout_strategy(config, user_id)
            logger.info(f"Feature {feature_name} rollout strategy result for user {user_id}: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Error checking feature access for {feature_name}: {str(e)}")
            return False
    
    async def _check_rollout_strategy(self, config: FeatureConfig, user_id: int) -> bool:
        """Check if user has access based on rollout strategy"""
        try:
            if config.rollout_strategy == RolloutStrategy.ALL_USERS:
                return True
            
            elif config.rollout_strategy == RolloutStrategy.USER_LIST:
                return user_id in config.target_users
            
            elif config.rollout_strategy == RolloutStrategy.ROLE_BASED:
                return await self._check_role_access(config.target_roles, user_id)
            
            elif config.rollout_strategy == RolloutStrategy.PERCENTAGE:
                # Use consistent hash-based percentage rollout
                user_hash = hash(f"{config.name}_{user_id}") % 100
                return user_hash < config.rollout_percentage
            
            elif config.rollout_strategy == RolloutStrategy.GRADUAL:
                # Gradual rollout combines role-based and percentage
                has_role_access = await self._check_role_access(["Beta Tester", "Admin", "Moderator"], user_id)
                if has_role_access:
                    return True
                
                # For non-beta users, use percentage
                user_hash = hash(f"{config.name}_{user_id}") % 100
                return user_hash < config.rollout_percentage
            
            return False
            
        except Exception as e:
            logger.error(f"Error in rollout strategy check: {str(e)}")
            return False
    
    async def _check_role_access(self, target_roles: List[str], user_id: int) -> bool:
        """Check if user has any of the target roles"""
        try:
            # Check app_role field first (User.app_role)
            from app.models.user import User
            user = self.db.query(User).filter(User.id == user_id).first()
            
            logger.info(f"Checking role access for user {user_id}, target_roles: {target_roles}")
            
            if user:
                logger.info(f"User {user_id} found - email: {user.email}, app_role: '{user.app_role}', is_admin(): {user.is_admin()}, is_beta_tester(): {user.is_beta_tester()}")
                
                # Check each target role explicitly
                for target_role in target_roles:
                    logger.info(f"Checking target role: '{target_role}'")
                    
                    if target_role == "Admin" and user.is_admin():
                        logger.info(f"User {user_id} granted access via Admin app_role (app_role='{user.app_role}')")
                        return True
                    if target_role == "Beta Tester" and user.is_beta_tester():
                        logger.info(f"User {user_id} granted access via Beta Tester app_role (app_role='{user.app_role}')")
                        return True
                    if target_role == "Moderator" and user.is_moderator():
                        logger.info(f"User {user_id} granted access via Moderator app_role (app_role='{user.app_role}')")
                        return True
            else:
                logger.warning(f"User {user_id} not found in database!")
            
            # Also check chat roles for backwards compatibility
            logger.info(f"Checking chat roles for user {user_id}")
            admin_chat_role = await is_user_admin(self.db, user_id)
            beta_chat_role = await is_user_beta_tester(self.db, user_id)
            logger.info(f"User {user_id} chat roles - admin: {admin_chat_role}, beta_tester: {beta_chat_role}")
            
            for target_role in target_roles:
                if target_role == "Admin" and admin_chat_role:
                    logger.info(f"User {user_id} granted access via Admin chat role")
                    return True
                if target_role == "Moderator" and await is_user_moderator(self.db, user_id):
                    logger.info(f"User {user_id} granted access via Moderator chat role")
                    return True
                if target_role == "Beta Tester" and beta_chat_role:
                    logger.info(f"User {user_id} granted access via Beta Tester chat role")
                    return True
            
            logger.info(f"User {user_id} denied access - no matching roles in app_role ('{user.app_role if user else 'USER_NOT_FOUND'}') or chat roles")
            return False
        except Exception as e:
            logger.error(f"Error checking role access: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    async def get_user_features(self, user_id: int) -> Dict[str, bool]:
        """
        Get all features and their availability status for a user
        
        Args:
            user_id: ID of the user
            
        Returns:
            Dict mapping feature names to availability status
        """
        try:
            logger.info(f"Getting all user features for user {user_id}")
            user_features = {}
            for feature_name in self._feature_configs.keys():
                is_enabled = await self.is_feature_enabled(feature_name, user_id)
                user_features[feature_name] = is_enabled
                logger.info(f"Feature {feature_name} for user {user_id}: {is_enabled}")
            
            logger.info(f"Final user features for user {user_id}: {user_features}")
            return user_features
        except Exception as e:
            logger.error(f"Error getting user features: {str(e)}")
            return {}
    
    async def get_feature_config(self, feature_name: str) -> Optional[Dict[str, Any]]:
        """Get configuration for a specific feature"""
        config = self._feature_configs.get(feature_name)
        if config:
            return asdict(config)
        return None
    
    async def get_all_features(self) -> Dict[str, Dict[str, Any]]:
        """Get all feature configurations"""
        return {name: asdict(config) for name, config in self._feature_configs.items()}
    
    async def update_feature_config(self, feature_name: str, updates: Dict[str, Any]) -> bool:
        """
        Update feature configuration (admin only)
        
        Args:
            feature_name: Name of the feature to update
            updates: Dictionary of configuration updates
            
        Returns:
            bool: True if update successful
        """
        try:
            if feature_name not in self._feature_configs:
                logger.error(f"Feature not found: {feature_name}")
                return False
            
            config = self._feature_configs[feature_name]
            
            # Update allowed fields
            if "status" in updates:
                config.status = FeatureStatus(updates["status"])
            if "rollout_percentage" in updates:
                config.rollout_percentage = updates["rollout_percentage"]
            if "target_users" in updates:
                config.target_users = updates["target_users"]
            if "description" in updates:
                config.description = updates["description"]
            if "metadata" in updates:
                config.metadata.update(updates["metadata"])
            
            logger.info(f"Updated feature config for {feature_name}: {updates}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating feature config: {str(e)}")
            return False
    
    async def add_user_to_feature(self, feature_name: str, user_id: int) -> bool:
        """Add a user to a specific feature's user list"""
        try:
            config = self._feature_configs.get(feature_name)
            if not config:
                return False
            
            if user_id not in config.target_users:
                config.target_users.append(user_id)
                logger.info(f"Added user {user_id} to feature {feature_name}")
            
            return True
        except Exception as e:
            logger.error(f"Error adding user to feature: {str(e)}")
            return False
    
    async def remove_user_from_feature(self, feature_name: str, user_id: int) -> bool:
        """Remove a user from a specific feature's user list"""
        try:
            config = self._feature_configs.get(feature_name)
            if not config:
                return False
            
            if user_id in config.target_users:
                config.target_users.remove(user_id)
                logger.info(f"Removed user {user_id} from feature {feature_name}")
            
            return True
        except Exception as e:
            logger.error(f"Error removing user from feature: {str(e)}")
            return False
    
    async def get_features_by_category(self, category: str) -> List[str]:
        """Get all features in a specific category"""
        try:
            features = []
            for name, config in self._feature_configs.items():
                if config.metadata.get("category") == category:
                    features.append(name)
            return features
        except Exception as e:
            logger.error(f"Error getting features by category: {str(e)}")
            return []
    
    async def get_beta_feature_usage_stats(self) -> Dict[str, Any]:
        """Get usage statistics for beta features"""
        try:
            stats = {
                "total_features": len(self._feature_configs),
                "enabled_features": 0,
                "beta_features": 0,
                "disabled_features": 0,
                "categories": {},
                "rollout_strategies": {}
            }
            
            for config in self._feature_configs.values():
                # Count by status
                if config.status == FeatureStatus.ENABLED:
                    stats["enabled_features"] += 1
                elif config.status == FeatureStatus.BETA:
                    stats["beta_features"] += 1
                elif config.status == FeatureStatus.DISABLED:
                    stats["disabled_features"] += 1
                
                # Count by category
                category = config.metadata.get("category", "Other")
                stats["categories"][category] = stats["categories"].get(category, 0) + 1
                
                # Count by rollout strategy
                strategy = config.rollout_strategy.value
                stats["rollout_strategies"][strategy] = stats["rollout_strategies"].get(strategy, 0) + 1
            
            return stats
        except Exception as e:
            logger.error(f"Error getting beta feature stats: {str(e)}")
            return {}


def create_feature_flag_decorator(feature_name: str):
    """
    Create a decorator for feature flag checking
    
    Args:
        feature_name: Name of the feature to check
        
    Returns:
        Decorator function
    """
    def decorator(func):
        from functools import wraps
        from fastapi import HTTPException, Depends
        from app.db.session import get_db
        from app.core.security import get_current_user
        
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                # Extract current_user and db from kwargs (FastAPI dependencies)
                current_user = kwargs.get('current_user')
                db = kwargs.get('db')
                
                if not current_user:
                    raise HTTPException(
                        status_code=401,
                        detail="Authentication required"
                    )
                
                if not db:
                    raise HTTPException(
                        status_code=500,
                        detail="Database session not available"
                    )
                
                feature_service = FeatureFlagService(db)
                has_access = await feature_service.is_feature_enabled(feature_name, current_user.id)
                
                if not has_access:
                    logger.warning(f"User {current_user.id} denied access to feature '{feature_name}'")
                    raise HTTPException(
                        status_code=403,
                        detail=f"Feature '{feature_name}' is not available for your account"
                    )
                
                logger.debug(f"User {current_user.id} granted access to feature '{feature_name}'")
                return await func(*args, **kwargs)
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Feature flag check error for {feature_name}: {str(e)}")
                logger.error(f"Exception details: {type(e).__name__}: {str(e)}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                raise HTTPException(
                    status_code=500,
                    detail="Error checking feature availability"
                )
        
        return wrapper
    return decorator


# Convenience decorators for specific features
require_advanced_analytics = create_feature_flag_decorator("advanced-analytics")
require_new_dashboard = create_feature_flag_decorator("new-dashboard")
require_experimental_trading = create_feature_flag_decorator("experimental-trading")
require_ai_insights = create_feature_flag_decorator("ai-insights")
require_broker_integration_v2 = create_feature_flag_decorator("broker-integration-v2")
require_member_chat = create_feature_flag_decorator("member-chat")
require_strategy_builder = create_feature_flag_decorator("strategy-builder")
require_atomik_trading_lab = create_feature_flag_decorator("atomik-trading-lab")