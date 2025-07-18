# app/api/v1/endpoints/admin.py
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
import logging
from datetime import datetime, timedelta
import httpx
import asyncio
import psutil  # For system metrics

from app.core.security import get_current_user
from app.models.user import User
from app.db.session import get_db
from app.models.promo_code import PromoCode
from app.services.promo_code_service import PromoCodeService

# Add new imports after existing imports
from sqlalchemy import func, and_, distinct, text, or_
from app.models.webhook import Webhook, WebhookLog
from app.models.strategy import ActivatedStrategy
from app.models.broker import BrokerAccount, BrokerCredentials
from app.models.subscription import Subscription
from app.models.chat import UserChatRole
from app.core.config import settings
from app.models.maintenance import MaintenanceSettings

router = APIRouter()
logger = logging.getLogger(__name__)

# Check if user is admin
async def get_admin_user(
    current_user: User = Depends(get_current_user)
) -> User:
    if not current_user.is_admin():
        logger.warning(f"Non-admin user {current_user.id} attempted admin action")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return current_user

# Pydantic models for request/response validation
class PromoCodeCreate(BaseModel):
    description: Optional[str] = Field(None, description="Description of the promo code")
    max_uses: Optional[int] = Field(None, description="Maximum number of times this code can be used")
    expiry_days: Optional[int] = Field(None, description="Number of days until the code expires")
    prefix: Optional[str] = Field("", description="Optional prefix for the code")
    code_length: Optional[int] = Field(8, description="Length of the generated code")

class PromoCodeUpdate(BaseModel):
    description: Optional[str] = None
    is_active: Optional[bool] = None
    max_uses: Optional[int] = None
    expires_at: Optional[datetime] = None

class PromoCodeResponse(BaseModel):
    id: int
    code: str
    description: Optional[str]
    is_active: bool
    max_uses: Optional[int]
    current_uses: int
    expires_at: Optional[datetime]
    created_by: Optional[int]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class PromoCodeStatsResponse(BaseModel):
    code: str
    total_uses: int
    max_uses: Optional[int]
    is_active: bool
    expires_at: Optional[str]
    created_at: str
    user_count: int
    remaining_uses: Any

class PromoCodeListResponse(BaseModel):
    total: int
    promo_codes: List[PromoCodeResponse]

class ResponseMessage(BaseModel):
    success: bool
    message: str

# Maintenance mode schemas
class MaintenanceSettingsResponse(BaseModel):
    is_enabled: bool
    message: Optional[str] = None
    created_by: int
    created_at: str
    updated_at: str

class MaintenanceSettingsUpdate(BaseModel):
    is_enabled: bool
    message: Optional[str] = None

# Add new response models for admin statistics
class AdminOverviewStats(BaseModel):
    total_users: int
    new_signups_today: int
    new_signups_week: int
    new_signups_month: int
    active_users: int
    trades_today: int
    total_revenue: float
    
class UserMetrics(BaseModel):
    total: int
    by_tier: Dict[str, int]
    growth_rate: float

# Add new models for comprehensive system status
class ServiceStatus(BaseModel):
    name: str
    status: str  # healthy, unhealthy, warning, unknown
    uptime: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    last_checked: Optional[str] = None

class SystemMetrics(BaseModel):
    cpu_usage: float
    memory_usage: float
    disk_usage: float
    active_connections: int

class SystemStatus(BaseModel):
    api_health: str
    database_status: str
    services: List[ServiceStatus]
    system_metrics: SystemMetrics
    uptime_percentage: float
    last_updated: str

@router.post("/promo-codes", response_model=PromoCodeResponse)
async def create_promo_code(
    data: PromoCodeCreate,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """Create a new promotional code (admin only)"""
    try:
        service = PromoCodeService(db)
        
        promo_code = service.create_promo_code(
            admin_id=admin_user.id,
            description=data.description,
            max_uses=data.max_uses,
            expiry_days=data.expiry_days,
            prefix=data.prefix,
            code_length=data.code_length
        )
        
        logger.info(f"Admin {admin_user.email} created promo code: {promo_code.code}")
        return promo_code
    
    except Exception as e:
        logger.error(f"Error creating promo code: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create promo code: {str(e)}"
        )

@router.get("/promo-codes", response_model=PromoCodeListResponse)
async def list_promo_codes(
    active_only: bool = False,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """List promotional codes (admin only)"""
    try:
        service = PromoCodeService(db)
        promo_codes = service.get_promo_codes(active_only=active_only, limit=limit, offset=offset)
        
        # Get total count
        total_query = db.query(PromoCode)
        if active_only:
            total_query = total_query.filter(PromoCode.is_active == True)
        total = total_query.count()
        
        return {
            "total": total,
            "promo_codes": promo_codes
        }
    
    except Exception as e:
        logger.error(f"Error listing promo codes: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list promo codes: {str(e)}"
        )

@router.get("/promo-codes/{code}", response_model=PromoCodeResponse)
async def get_promo_code(
    code: str,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """Get a specific promo code by code (admin only)"""
    try:
        service = PromoCodeService(db)
        promo_code = service.get_promo_code_by_code(code)
        
        if not promo_code:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Promo code not found"
            )
        
        return promo_code
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting promo code: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get promo code: {str(e)}"
        )

@router.get("/promo-codes/{code}/stats", response_model=Dict[str, Any])
async def get_promo_code_stats(
    code: str,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """Get usage statistics for a promo code (admin only)"""
    try:
        service = PromoCodeService(db)
        stats = service.get_promo_code_stats(code)
        
        if not stats["success"]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=stats["message"]
            )
        
        return stats
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting promo code stats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get promo code stats: {str(e)}"
        )

@router.put("/promo-codes/{code}", response_model=ResponseMessage)
async def update_promo_code(
    code: str,
    data: PromoCodeUpdate,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """Update a promo code (admin only)"""
    try:
        service = PromoCodeService(db)
        result = service.update_promo_code(code, data.model_dump(exclude_unset=True))
        
        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=result["message"]
            )
        
        logger.info(f"Admin {admin_user.email} updated promo code: {code}")
        return {
            "success": True,
            "message": "Promo code updated successfully"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating promo code: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update promo code: {str(e)}"
        )

@router.delete("/promo-codes/{code}", response_model=ResponseMessage)
async def deactivate_promo_code(
    code: str,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """Deactivate a promo code (admin only)"""
    try:
        service = PromoCodeService(db)
        result = service.deactivate_promo_code(code)
        
        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=result["message"]
            )
        
        logger.info(f"Admin {admin_user.email} deactivated promo code: {code}")
        return {
            "success": True,
            "message": "Promo code deactivated successfully"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deactivating promo code: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to deactivate promo code: {str(e)}"
        )

@router.post("/promo-codes/{code}/bulk-generate", response_model=Dict[str, Any])
async def bulk_generate_promo_codes(
    code: str,
    count: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """Bulk generate promo codes based on an existing template (admin only)"""
    try:
        # First get the template code
        service = PromoCodeService(db)
        template = service.get_promo_code_by_code(code)
        
        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Template promo code not found"
            )
        
        # Generate new codes with same settings
        generated_codes = []
        for _ in range(count):
            promo_code = service.create_promo_code(
                admin_id=admin_user.id,
                description=template.description,
                max_uses=template.max_uses,
                # If expires_at exists, calculate days remaining
                expiry_days=(template.expires_at - datetime.utcnow()).days if template.expires_at else None,
                prefix=code.split('-')[0] if '-' in code else "",
                code_length=len(code.split('-')[1]) if '-' in code else len(code)
            )
            generated_codes.append(promo_code.code)
        
        logger.info(f"Admin {admin_user.email} bulk generated {count} promo codes")
        return {
            "success": True,
            "count": len(generated_codes),
            "codes": generated_codes
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error bulk generating promo codes: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate promo codes: {str(e)}"
        )

# Add the new admin statistics endpoints before the existing promo code endpoints
@router.get("/overview/stats", response_model=AdminOverviewStats)
async def get_admin_overview_stats(
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """Get overview statistics for admin dashboard"""
    try:
        # Total users
        total_users = db.query(func.count(User.id)).scalar() or 0
        
        # New signups - today, this week, this month
        today = datetime.utcnow().date()
        week_ago = today - timedelta(days=7)
        month_ago = today - timedelta(days=30)
        
        new_signups_today = db.query(func.count(User.id)).filter(
            func.date(User.created_at) == today
        ).scalar() or 0
        
        new_signups_week = db.query(func.count(User.id)).filter(
            User.created_at >= week_ago
        ).scalar() or 0
        
        new_signups_month = db.query(func.count(User.id)).filter(
            User.created_at >= month_ago
        ).scalar() or 0
        
        # Active users (logged in within last 30 days)
        # Assuming you have a last_login field or similar
        # For now, let's count users with active subscriptions as active
        active_users = db.query(func.count(distinct(Subscription.user_id))).filter(
            Subscription.status == 'active'
        ).scalar() or 0
        
        # Trades today - count strategies triggered today
        trades_today = db.query(func.count(ActivatedStrategy.id)).filter(
            func.date(ActivatedStrategy.last_triggered) == today
        ).scalar() or 0
        
        # Total revenue (from active subscriptions)
        # This is a simplified calculation
        revenue_by_tier = {
            'starter': 47,
            'pro': 97,
            'elite': 197
        }
        
        total_revenue = 0
        for tier, price in revenue_by_tier.items():
            count = db.query(func.count(Subscription.id)).filter(
                Subscription.tier == tier,
                Subscription.status == 'active'
            ).scalar() or 0
            total_revenue += count * price
        
        return AdminOverviewStats(
            total_users=total_users,
            new_signups_today=new_signups_today,
            new_signups_week=new_signups_week,
            new_signups_month=new_signups_month,
            active_users=active_users,
            trades_today=trades_today,
            total_revenue=total_revenue
        )
        
    except Exception as e:
        logger.error(f"Error getting admin overview stats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get overview statistics: {str(e)}"
        )

@router.get("/metrics/users", response_model=UserMetrics)
async def get_user_metrics(
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """Get detailed user metrics for admin dashboard"""
    try:
        # Total users
        total = db.query(func.count(User.id)).scalar() or 0
        
        # Users by subscription tier
        by_tier = {}
        for tier in ['starter', 'pro', 'elite']:
            count = db.query(func.count(Subscription.id)).filter(
                Subscription.tier == tier,
                Subscription.status == 'active'
            ).scalar() or 0
            by_tier[tier] = count
        
        # Growth rate (comparing this month to last month)
        today = datetime.utcnow().date()
        this_month_start = today.replace(day=1)
        last_month_start = (this_month_start - timedelta(days=1)).replace(day=1)
        
        users_this_month = db.query(func.count(User.id)).filter(
            User.created_at >= this_month_start
        ).scalar() or 0
        
        users_last_month = db.query(func.count(User.id)).filter(
            and_(
                User.created_at >= last_month_start,
                User.created_at < this_month_start
            )
        ).scalar() or 0
        
        growth_rate = 0
        if users_last_month > 0:
            growth_rate = ((users_this_month - users_last_month) / users_last_month) * 100
        
        return UserMetrics(
            total=total,
            by_tier=by_tier,
            growth_rate=round(growth_rate, 2)
        )
        
    except Exception as e:
        logger.error(f"Error getting user metrics: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get user metrics: {str(e)}"
        )

@router.get("/system/status", response_model=SystemStatus)
async def get_system_status(
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """Get comprehensive system status for admin dashboard"""
    try:
        services = []
        
        # Check database connection
        try:
            db.execute(text("SELECT 1"))
            database_status = "healthy"
            logger.info("Database health check: healthy")
        except Exception as e:
            logger.error(f"Database health check failed: {str(e)}")
            database_status = "unhealthy"
        
        # Check API health - check if we can process requests
        api_health = "healthy"
        logger.info("API server health check: healthy (endpoint is responsive)")
        
        # Check Token Refresh Service
        logger.info("Checking Token Refresh Service...")
        token_service_status = await check_token_refresh_service()
        services.append(token_service_status)
        
        # Check Webhook Processing Service (based on recent activity)
        logger.info("Checking Webhook Processing Service...")
        webhook_status = check_webhook_service(db)
        services.append(webhook_status)
        
        # Get system metrics
        system_metrics = get_system_metrics()
        
        # Calculate simple uptime (in production, use proper monitoring)
        uptime_percentage = 99.99
        
        return SystemStatus(
            api_health=api_health,
            database_status=database_status,
            services=services,
            system_metrics=system_metrics,
            uptime_percentage=uptime_percentage,
            last_updated=datetime.utcnow().isoformat()
        )
        
    except Exception as e:
        logger.error(f"Error getting system status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get system status: {str(e)}"
        )

# Helper functions for system status
async def check_token_refresh_service() -> ServiceStatus:
    """Check the health of the token refresh service"""
    try:
        # The token refresh service URL can be configured via environment variable
        # Default to the Railway deployment URL
        token_service_url = getattr(settings, 'TOKEN_REFRESH_SERVICE_URL', 
                                   "https://token-refresh-service-production.up.railway.app")
        logger.info(f"Checking token refresh service at: {token_service_url}")
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{token_service_url}/health")
            
            # Handle both 200 OK and 503 Service Unavailable responses
            if response.status_code in [200, 503]:
                health_data = response.json()
                logger.info(f"Token refresh service health response: {health_data}")
                
                # Determine status based on response
                status = "healthy" if health_data.get("status") == "healthy" else "unhealthy"
                
                # Extract key metrics
                components = health_data.get("components", {})
                token_service = components.get("token_service", {})
                refresh_stats = components.get("refresh_statistics", {})
                database_info = components.get("database", {})
                
                # Build details including any error information
                details = {
                    "running": token_service.get("running", False),
                    "metrics": token_service.get("metrics", {}),
                    "database_connected": database_info.get("status") == "connected",
                    "database_status": database_info.get("status", "unknown"),
                    "refresh_stats": refresh_stats
                }
                
                # Add error information if present
                if "error" in health_data:
                    details["error"] = health_data["error"]
                if "error" in database_info:
                    details["database_error"] = database_info["error"]
                if "error" in token_service:
                    details["service_error"] = token_service["error"]
                
                return ServiceStatus(
                    name="Token Refresh Service",
                    status=status,
                    uptime="99.9%",  # You could calculate this from the service
                    details=details,
                    last_checked=datetime.utcnow().isoformat()
                )
            else:
                logger.warning(f"Token refresh service returned HTTP {response.status_code}")
                return ServiceStatus(
                    name="Token Refresh Service",
                    status="unhealthy",
                    uptime="0%",
                    details={"error": f"HTTP {response.status_code}", "response": response.text[:200]},
                    last_checked=datetime.utcnow().isoformat()
                )
                
    except httpx.RequestError as e:
        logger.error(f"Failed to connect to token refresh service: {str(e)}")
        return ServiceStatus(
            name="Token Refresh Service",
            status="unhealthy",
            uptime="0%",
            details={"error": "Connection failed", "message": str(e)},
            last_checked=datetime.utcnow().isoformat()
        )
    except Exception as e:
        logger.error(f"Error checking token refresh service: {str(e)}")
        return ServiceStatus(
            name="Token Refresh Service",
            status="unknown",
            details={"error": str(e)},
            last_checked=datetime.utcnow().isoformat()
        )

def check_webhook_service(db: Session) -> ServiceStatus:
    """Check webhook processing service health based on recent activity"""
    try:
        # Check if webhooks have been processed recently
        recent_threshold = datetime.utcnow() - timedelta(minutes=30)
        
        # Count recent webhook logs
        try:
            recent_webhooks = db.query(func.count(WebhookLog.id)).filter(
                WebhookLog.created_at >= recent_threshold
            ).scalar() or 0
            logger.info(f"Recent webhooks processed (last 30 min): {recent_webhooks}")
        except Exception as e:
            logger.warning(f"Could not query webhook logs: {str(e)}")
            recent_webhooks = 0
        
        # Count active webhooks
        active_webhooks = db.query(func.count(Webhook.id)).filter(
            Webhook.is_active == True
        ).scalar() or 0
        logger.info(f"Active webhooks configured: {active_webhooks}")
        
        # Determine status
        if active_webhooks == 0:
            status = "warning"
            details = {"message": "No active webhooks configured"}
        elif recent_webhooks > 0:
            status = "healthy"
            details = {
                "recent_webhooks_processed": recent_webhooks,
                "active_webhooks": active_webhooks
            }
        else:
            status = "warning"
            details = {
                "message": "No recent webhook activity",
                "active_webhooks": active_webhooks
            }
        
        return ServiceStatus(
            name="Webhook Processor",
            status=status,
            uptime="99.8%",  # You could track this more accurately
            details=details,
            last_checked=datetime.utcnow().isoformat()
        )
        
    except Exception as e:
        logger.error(f"Error checking webhook service: {str(e)}")
        return ServiceStatus(
            name="Webhook Processor",
            status="unknown",
            details={"error": str(e)},
            last_checked=datetime.utcnow().isoformat()
        )

def get_system_metrics() -> SystemMetrics:
    """Get current system resource metrics"""
    try:
        # Get CPU usage
        cpu_percent = psutil.cpu_percent(interval=1)
        
        # Get memory usage
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
        
        # Get disk usage
        disk = psutil.disk_usage('/')
        disk_percent = disk.percent
        
        # Get active database connections
        # This is a simplified count - in production, you'd want more detailed metrics
        from app.db.session import engine
        active_connections = engine.pool.size() if hasattr(engine.pool, 'size') else 0
        
        return SystemMetrics(
            cpu_usage=round(cpu_percent, 2),
            memory_usage=round(memory_percent, 2),
            disk_usage=round(disk_percent, 2),
            active_connections=active_connections
        )
        
    except Exception as e:
        logger.error(f"Error getting system metrics: {str(e)}")
        # Return default values on error
        return SystemMetrics(
            cpu_usage=0.0,
            memory_usage=0.0,
            disk_usage=0.0,
            active_connections=0
        )

# New unified user management endpoints
class UserCompleteResponse(BaseModel):
    id: int
    username: str
    email: str
    full_name: Optional[str]
    phone: Optional[str]
    is_active: bool
    app_role: Optional[str]
    profile_picture: Optional[str]
    created_at: datetime
    last_login: Optional[datetime] = None
    subscription: Optional[Dict[str, Any]]
    roles: List[str]
    connected_accounts: int
    
    class Config:
        from_attributes = True

class UsersCompleteResponse(BaseModel):
    users: List[UserCompleteResponse]
    total: int
    available_roles: List[str]

class RoleAssignmentRequest(BaseModel):
    role_name: str
    role_color: str = "#4CAF50"
    role_priority: int = 0

class BetaToggleRequest(BaseModel):
    is_beta: bool

class UserUpdateRequest(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    full_name: Optional[str] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None
    app_role: Optional[str] = None

@router.get("/users/complete", response_model=UsersCompleteResponse)
async def get_users_complete(
    search: str = "",
    status_param: str = Query("all", alias="status"),
    roles: List[str] = Query([]),
    subscription: List[str] = Query([]),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """Get complete user data with roles, subscriptions, and account info"""
    try:
        # Start with a simple base query
        query = db.query(User)
        
        # Apply search filter
        if search:
            search_filter = or_(
                User.username.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%"),
                User.full_name.ilike(f"%{search}%")
            )
            query = query.filter(search_filter)
        
        # Apply status filter
        if status_param != "all":
            if status_param == "active":
                query = query.filter(User.is_active == True)
            elif status_param == "inactive":
                query = query.filter(User.is_active == False)
            elif status_param == "admin":
                query = query.filter(User.app_role == 'admin')
        
        # Get total count
        total = query.count()
        
        # Apply pagination
        users = query.offset(offset).limit(limit).all()
        
        # Build complete user objects
        user_responses = []
        for user in users:
            try:
                # Get user roles safely
                user_roles = []
                try:
                    roles_query = db.query(UserChatRole.role_name).filter(
                        UserChatRole.user_id == user.id,
                        UserChatRole.is_active == True
                    ).all()
                    user_roles = [role[0] for role in roles_query]
                except Exception as role_error:
                    logger.warning(f"Could not fetch roles for user {user.id}: {role_error}")
                    user_roles = []
                
                # Add admin role if app_role is admin
                if user.is_admin() and "Admin" not in user_roles:
                    user_roles.append("Admin")
                
                # Ensure at least "User" role
                if not user_roles:
                    user_roles = ["User"]
                
                # Get connected accounts count safely
                connected_accounts = 0
                try:
                    connected_accounts = db.query(func.count(BrokerAccount.id)).filter(
                        BrokerAccount.user_id == user.id
                    ).scalar() or 0
                except Exception as broker_error:
                    logger.warning(f"Could not fetch broker accounts for user {user.id}: {broker_error}")
                    connected_accounts = 0
                
                # Get subscription data safely
                subscription_data = None
                try:
                    user_subscription = db.query(Subscription).filter(Subscription.user_id == user.id).first()
                    if user_subscription:
                        subscription_data = {
                            "tier": user_subscription.tier,
                            "status": user_subscription.status,
                            "billing_interval": getattr(user_subscription, 'billing_interval', None)
                        }
                except Exception as sub_error:
                    logger.warning(f"Could not fetch subscription for user {user.id}: {sub_error}")
                    subscription_data = None
                
                user_response = UserCompleteResponse(
                    id=user.id,
                    username=user.username or "",
                    email=user.email or "",
                    full_name=user.full_name,
                    phone=user.phone,
                    is_active=user.is_active,
                    app_role=user.app_role,
                    profile_picture=user.profile_picture,
                    created_at=user.created_at,
                    last_login=None,
                    subscription=subscription_data,
                    roles=user_roles,
                    connected_accounts=connected_accounts
                )
                user_responses.append(user_response)
                
            except Exception as user_error:
                logger.error(f"Error processing user {user.id}: {user_error}")
                continue
        
        # Get available roles
        available_roles = ["Admin", "Manager", "Support", "Beta Tester", "User"]
        
        return UsersCompleteResponse(
            users=user_responses,
            total=total,
            available_roles=available_roles
        )
        
    except Exception as e:
        logger.error(f"Error getting complete users data: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get users data: {str(e)}"
        )

@router.post("/users/{user_id}/role", response_model=ResponseMessage)
async def assign_user_role(
    user_id: int,
    role_data: RoleAssignmentRequest,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """Assign a role to a user"""
    try:
        # Check if user exists
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Check if role already exists for this user
        existing_role = db.query(UserChatRole).filter(
            UserChatRole.user_id == user_id,
            UserChatRole.role_name == role_data.role_name,
            UserChatRole.is_active == True
        ).first()
        
        if existing_role:
            return ResponseMessage(
                success=True,
                message=f"User already has the {role_data.role_name} role"
            )
        
        # Use the appropriate role service function based on role type
        from app.services.chat_role_service import assign_admin_role, assign_moderator_role, assign_beta_tester_role
        
        if role_data.role_name == "Admin":
            await assign_admin_role(db, user_id, admin_user.id)
        elif role_data.role_name == "Moderator":
            await assign_moderator_role(db, user_id, admin_user.id)
        elif role_data.role_name == "Beta Tester":
            await assign_beta_tester_role(db, user_id, admin_user.id)
        else:
            # For other roles, create manually (no app_role sync needed)
            new_role = UserChatRole(
                user_id=user_id,
                role_name=role_data.role_name,
                role_color=role_data.role_color,
                role_priority=role_data.role_priority,
                assigned_by=admin_user.id
            )
            db.add(new_role)
            db.commit()
        
        logger.info(f"Admin {admin_user.email} assigned role {role_data.role_name} to user {user.email}")
        
        return ResponseMessage(
            success=True,
            message=f"Role {role_data.role_name} assigned successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error assigning role: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to assign role: {str(e)}"
        )

@router.delete("/users/{user_id}/role/{role_name}", response_model=ResponseMessage)
async def remove_user_role(
    user_id: int,
    role_name: str,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """Remove a role from a user"""
    try:
        # Find the role assignment
        role_assignment = db.query(UserChatRole).filter(
            UserChatRole.user_id == user_id,
            UserChatRole.role_name == role_name,
            UserChatRole.is_active == True
        ).first()
        
        if not role_assignment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Role assignment not found"
            )
        
        # Use the appropriate role service function based on role type
        from app.services.chat_role_service import remove_admin_role, remove_moderator_role, remove_beta_tester_role
        
        if role_name == "Admin":
            await remove_admin_role(db, user_id)
        elif role_name == "Moderator":
            await remove_moderator_role(db, user_id)
        elif role_name == "Beta Tester":
            await remove_beta_tester_role(db, user_id)
        else:
            # For other roles, deactivate manually (no app_role sync needed)
            role_assignment.is_active = False
            db.commit()
        
        logger.info(f"Admin {admin_user.email} removed role {role_name} from user {user_id}")
        
        return ResponseMessage(
            success=True,
            message=f"Role {role_name} removed successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing role: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to remove role: {str(e)}"
        )

@router.post("/users/{user_id}/beta", response_model=ResponseMessage)
async def toggle_beta_access(
    user_id: int,
    beta_data: BetaToggleRequest,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """Toggle beta tester access for a user"""
    try:
        # Check if user exists
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        beta_role_name = "Beta Tester"
        
        # Check current beta status
        existing_beta_role = db.query(UserChatRole).filter(
            UserChatRole.user_id == user_id,
            UserChatRole.role_name == beta_role_name,
            UserChatRole.is_active == True
        ).first()
        
        if beta_data.is_beta and not existing_beta_role:
            # Add beta tester role (this will also update app_role)
            from app.services.chat_role_service import assign_beta_tester_role
            await assign_beta_tester_role(db, user_id, admin_user.id)
            action = "added"
            
        elif not beta_data.is_beta and existing_beta_role:
            # Remove beta tester role (this will also update app_role)
            from app.services.chat_role_service import remove_beta_tester_role
            await remove_beta_tester_role(db, user_id)
            action = "removed"
            
        else:
            # No change needed
            status_text = "already has" if beta_data.is_beta else "doesn't have"
            return ResponseMessage(
                success=True,
                message=f"User {status_text} beta access"
            )
        
        db.commit()
        
        logger.info(f"Admin {admin_user.email} {action} beta access for user {user.email}")
        
        return ResponseMessage(
            success=True,
            message=f"Beta access {action} successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error toggling beta access: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to toggle beta access: {str(e)}"
        )

@router.post("/users/bulk", response_model=ResponseMessage)
async def bulk_user_operations(
    user_ids: List[int],
    operation: str,
    operation_data: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """Perform bulk operations on multiple users"""
    try:
        if operation not in ["activate", "deactivate", "assign_role", "remove_role", "toggle_beta"]:
            raise HTTPException(
                status_code=400,
                detail="Invalid bulk operation"
            )
        
        affected_users = 0
        
        for user_id in user_ids:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                continue
                
            if operation == "activate":
                user.is_active = True
                affected_users += 1
                
            elif operation == "deactivate":
                user.is_active = False
                affected_users += 1
                
            elif operation == "assign_role" and operation_data:
                role_name = operation_data.get("role_name")
                if role_name:
                    existing_role = db.query(UserChatRole).filter(
                        UserChatRole.user_id == user_id,
                        UserChatRole.role_name == role_name,
                        UserChatRole.is_active == True
                    ).first()
                    
                    if not existing_role:
                        new_role = UserChatRole(
                            user_id=user_id,
                            role_name=role_name,
                            role_color=operation_data.get("role_color", "#4CAF50"),
                            role_priority=operation_data.get("role_priority", 0),
                            assigned_by=admin_user.id
                        )
                        db.add(new_role)
                        affected_users += 1
        
        db.commit()
        
        logger.info(f"Admin {admin_user.email} performed bulk {operation} on {affected_users} users")
        
        return ResponseMessage(
            success=True,
            message=f"Bulk operation completed. {affected_users} users affected."
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error performing bulk operation: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to perform bulk operation: {str(e)}"
        )


@router.put("/users/{user_id}", response_model=ResponseMessage)
async def update_user(
    user_id: int,
    user_data: UserUpdateRequest,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """Update a user's information (admin only)"""
    try:
        # Find the user to update
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Track what fields are being updated
        updated_fields = []
        
        # Update fields if provided
        if user_data.username is not None:
            # Check if username is already taken by another user
            existing_user = db.query(User).filter(
                User.username == user_data.username,
                User.id != user_id
            ).first()
            if existing_user:
                raise HTTPException(status_code=400, detail="Username already taken")
            user.username = user_data.username
            updated_fields.append("username")
        
        if user_data.email is not None:
            # Check if email is already taken by another user
            existing_user = db.query(User).filter(
                User.email == user_data.email,
                User.id != user_id
            ).first()
            if existing_user:
                raise HTTPException(status_code=400, detail="Email already taken")
            user.email = user_data.email
            updated_fields.append("email")
        
        if user_data.full_name is not None:
            user.full_name = user_data.full_name
            updated_fields.append("full_name")
        
        if user_data.phone is not None:
            user.phone = user_data.phone
            updated_fields.append("phone")
        
        if user_data.is_active is not None:
            user.is_active = user_data.is_active
            updated_fields.append("is_active")
        
        if user_data.app_role is not None:
            # Validate app_role values
            valid_roles = ['admin', 'moderator', 'beta_tester', None]
            if user_data.app_role not in valid_roles and user_data.app_role != "":
                raise HTTPException(status_code=400, detail=f"Invalid app_role. Must be one of: {valid_roles}")
            
            # Convert empty string to None
            user.app_role = user_data.app_role if user_data.app_role != "" else None
            updated_fields.append("app_role")
        
        # Update the updated_at timestamp
        user.updated_at = datetime.utcnow()
        
        # Commit changes
        db.commit()
        
        logger.info(f"Admin {admin_user.id} updated user {user_id}. Fields: {', '.join(updated_fields)}")
        
        return ResponseMessage(
            message=f"User {user.username} updated successfully. Updated fields: {', '.join(updated_fields) if updated_fields else 'none'}"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating user {user_id}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update user: {str(e)}"
        )

# ============ MAINTENANCE MODE ENDPOINTS ============

@router.get("/maintenance", response_model=MaintenanceSettingsResponse)
def get_maintenance_settings(
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """Get current maintenance settings"""
    try:
        maintenance = db.query(MaintenanceSettings).order_by(MaintenanceSettings.updated_at.desc()).first()
        
        if not maintenance:
            # Return default settings if none exist
            return MaintenanceSettingsResponse(
                is_enabled=False,
                message=None,
                created_by=admin_user.id,
                created_at="",
                updated_at=""
            )
        
        return MaintenanceSettingsResponse(
            is_enabled=maintenance.is_enabled,
            message=maintenance.message,
            created_by=maintenance.created_by,
            created_at=maintenance.created_at.isoformat(),
            updated_at=maintenance.updated_at.isoformat()
        )
        
    except Exception as e:
        logger.error(f"Error getting maintenance settings: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving maintenance settings"
        )

@router.put("/maintenance", response_model=MaintenanceSettingsResponse)
def update_maintenance_settings(
    settings: MaintenanceSettingsUpdate,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """Update maintenance settings"""
    try:
        # Get the latest maintenance settings or create new one
        maintenance = db.query(MaintenanceSettings).order_by(MaintenanceSettings.updated_at.desc()).first()
        
        if maintenance:
            # Update existing settings
            maintenance.is_enabled = settings.is_enabled
            maintenance.message = settings.message
            maintenance.created_by = admin_user.id
        else:
            # Create new settings
            maintenance = MaintenanceSettings(
                is_enabled=settings.is_enabled,
                message=settings.message,
                created_by=admin_user.id
            )
            db.add(maintenance)
        
        db.commit()
        db.refresh(maintenance)
        
        logger.info(f"Maintenance mode {'enabled' if settings.is_enabled else 'disabled'} by user {admin_user.username}")
        
        return MaintenanceSettingsResponse(
            is_enabled=maintenance.is_enabled,
            message=maintenance.message,
            created_by=maintenance.created_by,
            created_at=maintenance.created_at.isoformat(),
            updated_at=maintenance.updated_at.isoformat()
        )
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating maintenance settings: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error updating maintenance settings"
        )

@router.get("/maintenance/status")
def get_maintenance_status(db: Session = Depends(get_db)):
    """Public endpoint to check if maintenance mode is enabled (no auth required)"""
    try:
        maintenance = db.query(MaintenanceSettings).order_by(MaintenanceSettings.updated_at.desc()).first()
        
        if not maintenance:
            return {"is_enabled": False, "message": None}
        
        return {
            "is_enabled": maintenance.is_enabled,
            "message": maintenance.message
        }
        
    except Exception as e:
        logger.error(f"Error getting maintenance status: {e}")
        return {"is_enabled": False, "message": None}