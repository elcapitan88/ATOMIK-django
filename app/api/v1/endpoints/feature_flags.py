"""
Feature Flags API Endpoints

Provides REST API endpoints for managing feature flags in the beta testing system.
Includes both user-facing endpoints for checking feature availability and admin
endpoints for managing feature configurations.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Dict, Any, List, Optional
import logging

from app.db.session import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.services.feature_flag_service import FeatureFlagService, FeatureStatus, RolloutStrategy
from app.services.chat_role_service import is_user_admin
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


# Pydantic models for request/response
class FeatureUpdateRequest(BaseModel):
    status: Optional[str] = None
    rollout_percentage: Optional[int] = None
    target_users: Optional[List[int]] = None
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class FeatureAccessResponse(BaseModel):
    feature_name: str
    enabled: bool
    reason: Optional[str] = None


class UserFeaturesResponse(BaseModel):
    user_id: int
    is_beta_tester: bool
    features: Dict[str, bool]
    feature_count: int


class FeatureConfigResponse(BaseModel):
    name: str
    status: str
    rollout_strategy: str
    rollout_percentage: int
    target_users: List[int]
    target_roles: List[str]
    description: str
    dependencies: List[str]
    metadata: Dict[str, Any]


class FeatureStatsResponse(BaseModel):
    total_features: int
    enabled_features: int
    beta_features: int
    disabled_features: int
    categories: Dict[str, int]
    rollout_strategies: Dict[str, int]


# User-facing endpoints
@router.get("/features/me", response_model=UserFeaturesResponse)
async def get_my_features(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all features available to the current user"""
    try:
        feature_service = FeatureFlagService(db)
        user_features = await feature_service.get_user_features(current_user.id)
        
        # Debug logging for member-chat feature
        member_chat_enabled = await feature_service.is_feature_enabled("member-chat", current_user.id)
        logger.info(f"User {current_user.id} (app_role: {current_user.app_role}) - member-chat enabled: {member_chat_enabled}")
        logger.info(f"User features returned: {user_features}")
        
        # Check if user is beta tester
        from app.services.chat_role_service import is_user_beta_tester
        is_beta = await is_user_beta_tester(db, current_user.id)
        
        return UserFeaturesResponse(
            user_id=current_user.id,
            is_beta_tester=is_beta,
            features=user_features,
            feature_count=len([f for f in user_features.values() if f])
        )
    except Exception as e:
        logger.error(f"Error getting user features: {str(e)}")
        raise HTTPException(status_code=500, detail="Error retrieving user features")


@router.get("/features/{feature_name}/access", response_model=FeatureAccessResponse)
async def check_feature_access(
    feature_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Check if current user has access to a specific feature"""
    try:
        feature_service = FeatureFlagService(db)
        has_access = await feature_service.is_feature_enabled(feature_name, current_user.id)
        
        reason = None
        if not has_access:
            config = await feature_service.get_feature_config(feature_name)
            if not config:
                reason = "Feature not found"
            elif config["status"] == "disabled":
                reason = "Feature is currently disabled"
            else:
                reason = "User does not meet feature requirements"
        
        return FeatureAccessResponse(
            feature_name=feature_name,
            enabled=has_access,
            reason=reason
        )
    except Exception as e:
        logger.error(f"Error checking feature access: {str(e)}")
        raise HTTPException(status_code=500, detail="Error checking feature access")


@router.get("/features/categories/{category}")
async def get_features_by_category(
    category: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all features in a specific category available to the user"""
    try:
        feature_service = FeatureFlagService(db)
        category_features = await feature_service.get_features_by_category(category)
        
        # Check user access for each feature
        user_category_features = {}
        for feature in category_features:
            has_access = await feature_service.is_feature_enabled(feature, current_user.id)
            user_category_features[feature] = has_access
        
        return {
            "category": category,
            "features": user_category_features,
            "available_count": len([f for f in user_category_features.values() if f])
        }
    except Exception as e:
        logger.error(f"Error getting category features: {str(e)}")
        raise HTTPException(status_code=500, detail="Error retrieving category features")


# Admin-only endpoints
@router.get("/admin/features", response_model=List[FeatureConfigResponse])
async def get_all_feature_configs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all feature configurations (admin only)"""
    try:
        # Check admin access (both app_role and chat role)
        if not current_user.is_admin() and not await is_user_admin(db, current_user.id):
            raise HTTPException(status_code=403, detail="Admin access required")
        
        feature_service = FeatureFlagService(db)
        all_features = await feature_service.get_all_features()
        
        return [
            FeatureConfigResponse(**config) 
            for config in all_features.values()
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting feature configs: {str(e)}")
        raise HTTPException(status_code=500, detail="Error retrieving feature configurations")


@router.get("/admin/features/{feature_name}", response_model=FeatureConfigResponse)
async def get_feature_config(
    feature_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get configuration for a specific feature (admin only)"""
    try:
        # Check admin access (both app_role and chat role)
        if not current_user.is_admin() and not await is_user_admin(db, current_user.id):
            raise HTTPException(status_code=403, detail="Admin access required")
        
        feature_service = FeatureFlagService(db)
        config = await feature_service.get_feature_config(feature_name)
        
        if not config:
            raise HTTPException(status_code=404, detail="Feature not found")
        
        return FeatureConfigResponse(**config)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting feature config: {str(e)}")
        raise HTTPException(status_code=500, detail="Error retrieving feature configuration")


@router.put("/admin/features/{feature_name}")
async def update_feature_config(
    feature_name: str,
    updates: FeatureUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update feature configuration (admin only)"""
    try:
        # Check admin access (both app_role and chat role)
        if not current_user.is_admin() and not await is_user_admin(db, current_user.id):
            raise HTTPException(status_code=403, detail="Admin access required")
        
        feature_service = FeatureFlagService(db)
        
        # Validate status if provided
        if updates.status:
            try:
                FeatureStatus(updates.status)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid feature status")
        
        # Validate rollout percentage
        if updates.rollout_percentage is not None:
            if not 0 <= updates.rollout_percentage <= 100:
                raise HTTPException(status_code=400, detail="Rollout percentage must be between 0 and 100")
        
        update_dict = updates.dict(exclude_unset=True)
        success = await feature_service.update_feature_config(feature_name, update_dict)
        
        if not success:
            raise HTTPException(status_code=404, detail="Feature not found")
        
        return {"success": True, "message": f"Feature {feature_name} updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating feature config: {str(e)}")
        raise HTTPException(status_code=500, detail="Error updating feature configuration")


@router.post("/admin/features/{feature_name}/users/{user_id}")
async def add_user_to_feature(
    feature_name: str,
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add a user to a specific feature's user list (admin only)"""
    try:
        # Check admin access (both app_role and chat role)
        if not current_user.is_admin() and not await is_user_admin(db, current_user.id):
            raise HTTPException(status_code=403, detail="Admin access required")
        
        feature_service = FeatureFlagService(db)
        success = await feature_service.add_user_to_feature(feature_name, user_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="Feature not found")
        
        return {"success": True, "message": f"User {user_id} added to feature {feature_name}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding user to feature: {str(e)}")
        raise HTTPException(status_code=500, detail="Error adding user to feature")


@router.delete("/admin/features/{feature_name}/users/{user_id}")
async def remove_user_from_feature(
    feature_name: str,
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Remove a user from a specific feature's user list (admin only)"""
    try:
        # Check admin access (both app_role and chat role)
        if not current_user.is_admin() and not await is_user_admin(db, current_user.id):
            raise HTTPException(status_code=403, detail="Admin access required")
        
        feature_service = FeatureFlagService(db)
        success = await feature_service.remove_user_from_feature(feature_name, user_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="Feature not found")
        
        return {"success": True, "message": f"User {user_id} removed from feature {feature_name}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing user from feature: {str(e)}")
        raise HTTPException(status_code=500, detail="Error removing user from feature")


@router.get("/admin/features/stats", response_model=FeatureStatsResponse)
async def get_feature_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get feature usage statistics (admin only)"""
    try:
        # Check admin access (both app_role and chat role)
        if not current_user.is_admin() and not await is_user_admin(db, current_user.id):
            raise HTTPException(status_code=403, detail="Admin access required")
        
        feature_service = FeatureFlagService(db)
        stats = await feature_service.get_beta_feature_usage_stats()
        
        return FeatureStatsResponse(**stats)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting feature stats: {str(e)}")
        raise HTTPException(status_code=500, detail="Error retrieving feature statistics")


@router.post("/admin/features/{feature_name}/enable")
async def enable_feature(
    feature_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Enable a feature for all users (admin only)"""
    try:
        # Check admin access (both app_role and chat role)
        if not current_user.is_admin() and not await is_user_admin(db, current_user.id):
            raise HTTPException(status_code=403, detail="Admin access required")
        
        feature_service = FeatureFlagService(db)
        success = await feature_service.update_feature_config(
            feature_name, 
            {"status": "enabled", "rollout_strategy": "all_users"}
        )
        
        if not success:
            raise HTTPException(status_code=404, detail="Feature not found")
        
        return {"success": True, "message": f"Feature {feature_name} enabled for all users"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error enabling feature: {str(e)}")
        raise HTTPException(status_code=500, detail="Error enabling feature")


@router.post("/admin/features/{feature_name}/disable")
async def disable_feature(
    feature_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Disable a feature for all users (admin only)"""
    try:
        # Check admin access (both app_role and chat role)
        if not current_user.is_admin() and not await is_user_admin(db, current_user.id):
            raise HTTPException(status_code=403, detail="Admin access required")
        
        feature_service = FeatureFlagService(db)
        success = await feature_service.update_feature_config(
            feature_name, 
            {"status": "disabled"}
        )
        
        if not success:
            raise HTTPException(status_code=404, detail="Feature not found")
        
        return {"success": True, "message": f"Feature {feature_name} disabled for all users"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error disabling feature: {str(e)}")
        raise HTTPException(status_code=500, detail="Error disabling feature")


@router.get("/admin/debug/user/{user_id}")
async def debug_user_access(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Debug user role and feature access (admin only)"""
    try:
        # Check admin access (both app_role and chat role)
        if not current_user.is_admin() and not await is_user_admin(db, current_user.id):
            raise HTTPException(status_code=403, detail="Admin access required")
        
        # Get user details
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Check chat roles
        from app.services.chat_role_service import is_user_admin, is_user_moderator, is_user_beta_tester
        admin_chat_role = await is_user_admin(db, user_id)
        moderator_chat_role = await is_user_moderator(db, user_id)
        beta_chat_role = await is_user_beta_tester(db, user_id)
        
        # Get feature access
        feature_service = FeatureFlagService(db)
        all_features = await feature_service.get_user_features(user_id)
        
        return {
            "user_id": user_id,
            "email": user.email,
            "app_role": user.app_role,
            "app_role_checks": {
                "is_admin": user.is_admin(),
                "is_moderator": user.is_moderator(),
                "is_beta_tester": user.is_beta_tester()
            },
            "chat_roles": {
                "admin": admin_chat_role,
                "moderator": moderator_chat_role,
                "beta_tester": beta_chat_role
            },
            "feature_access": all_features,
            "strategy_builder_access": {
                "enabled": all_features.get("strategy-builder", False),
                "config": await feature_service.get_feature_config("strategy-builder")
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error debugging user access: {str(e)}")
        raise HTTPException(status_code=500, detail="Error debugging user access")


@router.get("/admin/debug/current-user")
async def debug_current_user_access(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Debug current user role and feature access"""
    try:
        # Check chat roles
        from app.services.chat_role_service import is_user_admin, is_user_moderator, is_user_beta_tester
        admin_chat_role = await is_user_admin(db, current_user.id)
        moderator_chat_role = await is_user_moderator(db, current_user.id)
        beta_chat_role = await is_user_beta_tester(db, current_user.id)
        
        # Get feature access
        feature_service = FeatureFlagService(db)
        all_features = await feature_service.get_user_features(current_user.id)
        
        return {
            "user_id": current_user.id,
            "email": current_user.email,
            "app_role": current_user.app_role,
            "app_role_checks": {
                "is_admin": current_user.is_admin(),
                "is_moderator": current_user.is_moderator(),
                "is_beta_tester": current_user.is_beta_tester()
            },
            "chat_roles": {
                "admin": admin_chat_role,
                "moderator": moderator_chat_role,
                "beta_tester": beta_chat_role
            },
            "feature_access": all_features,
            "strategy_builder_access": {
                "enabled": all_features.get("strategy-builder", False),
                "config": await feature_service.get_feature_config("strategy-builder")
            }
        }
    except Exception as e:
        logger.error(f"Error debugging current user access: {str(e)}")
        raise HTTPException(status_code=500, detail="Error debugging current user access")