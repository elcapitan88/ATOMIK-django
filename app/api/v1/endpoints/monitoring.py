from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any
import logging

from ....core.memory_monitor import memory_monitor
from ....core.redis_manager import redis_manager
from ....services.trading_service import order_monitoring_service
from ....services.distributed_lock import AccountLockManager
from ....core.security import get_current_user
from ....models.user import User
from ....db.session import engine
from ....core.alert_manager import alert_manager
from ....core.circuit_breaker import circuit_breaker_manager
from ....core.rollback_manager import rollback_manager
from ....core.graceful_shutdown import shutdown_manager

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/health")
async def get_system_health():
    """Get comprehensive system health status - public endpoint"""
    try:
        health_status = {
            "status": "healthy",
            "timestamp": memory_monitor.get_current_metrics().timestamp.isoformat() if memory_monitor.get_current_metrics() else None,
            "services": {}
        }
        
        # Memory status
        try:
            memory_stats = memory_monitor.get_stats()
            health_status["services"]["memory"] = {
                "status": "healthy" if memory_stats.get("status") == "running" else "degraded",
                "current_mb": memory_stats.get("current", {}).get("rss_mb"),
                "percent": memory_stats.get("current", {}).get("percent"),
                "alerts": memory_stats.get("alerts", {})
            }
        except Exception as e:
            health_status["services"]["memory"] = {"status": "error", "error": str(e)}
            health_status["status"] = "degraded"
        
        # Redis status
        try:
            redis_stats = redis_manager.get_stats()
            health_status["services"]["redis"] = {
                "status": redis_stats.get("status", "unknown"),
                "available": redis_manager.is_available()
            }
            if not redis_manager.is_available():
                health_status["status"] = "degraded"
        except Exception as e:
            health_status["services"]["redis"] = {"status": "error", "error": str(e)}
            health_status["status"] = "degraded"
        
        # Database status
        try:
            if engine and engine.pool:
                pool_status = engine.pool.status()
                health_status["services"]["database"] = {
                    "status": "healthy",
                    "pool_size": engine.pool.size(),
                    "checked_in": engine.pool.checkedin(),
                    "checked_out": engine.pool.checkedout(),
                    "overflow": engine.pool.overflow(),
                    "invalid": engine.pool.invalid()
                }
            else:
                health_status["services"]["database"] = {"status": "error", "error": "Engine not available"}
                health_status["status"] = "critical"
        except Exception as e:
            health_status["services"]["database"] = {"status": "error", "error": str(e)}
            health_status["status"] = "degraded"
        
        # Order monitoring status
        try:
            monitoring_stats = order_monitoring_service.get_stats()
            health_status["services"]["order_monitoring"] = {
                "status": "healthy" if monitoring_stats.get("running") else "stopped",
                "active_orders": monitoring_stats.get("active_monitors", 0)
            }
        except Exception as e:
            health_status["services"]["order_monitoring"] = {"status": "error", "error": str(e)}
            health_status["status"] = "degraded"
        
        return health_status
        
    except Exception as e:
        logger.error(f"Error getting system health: {e}")
        raise HTTPException(status_code=500, detail="Health check failed")

@router.get("/metrics")
async def get_system_metrics(current_user: User = Depends(get_current_user)):
    """Get detailed system metrics - requires authentication"""
    try:
        metrics = {
            "timestamp": memory_monitor.get_current_metrics().timestamp.isoformat() if memory_monitor.get_current_metrics() else None,
            "memory": {},
            "redis": {},
            "database": {},
            "order_monitoring": {}
        }
        
        # Detailed memory metrics
        try:
            memory_stats = memory_monitor.get_stats()
            metrics["memory"] = memory_stats
        except Exception as e:
            metrics["memory"] = {"error": str(e)}
        
        # Detailed Redis metrics
        try:
            redis_stats = redis_manager.get_stats()
            metrics["redis"] = redis_stats
        except Exception as e:
            metrics["redis"] = {"error": str(e)}
        
        # Detailed database metrics
        try:
            if engine and engine.pool:
                metrics["database"] = {
                    "pool_status": engine.pool.status(),
                    "pool_size": engine.pool.size(),
                    "checked_in": engine.pool.checkedin(),
                    "checked_out": engine.pool.checkedout(),
                    "overflow": engine.pool.overflow(),
                    "invalid": engine.pool.invalid(),
                    "connection_info": {
                        "url": str(engine.url).replace(engine.url.password, "*****") if engine.url.password else str(engine.url)
                    }
                }
            else:
                metrics["database"] = {"error": "Engine not available"}
        except Exception as e:
            metrics["database"] = {"error": str(e)}
        
        # Detailed order monitoring metrics
        try:
            monitoring_stats = order_monitoring_service.get_stats()
            metrics["order_monitoring"] = monitoring_stats
        except Exception as e:
            metrics["order_monitoring"] = {"error": str(e)}
        
        return metrics
        
    except Exception as e:
        logger.error(f"Error getting system metrics: {e}")
        raise HTTPException(status_code=500, detail="Metrics collection failed")

@router.get("/memory/history")
async def get_memory_history(
    limit: int = 50,
    current_user: User = Depends(get_current_user)
):
    """Get memory usage history - requires authentication"""
    try:
        history = memory_monitor.get_metrics_history(limit)
        return {
            "count": len(history),
            "limit": limit,
            "history": [
                {
                    "rss_mb": round(m.rss_mb, 2),
                    "vms_mb": round(m.vms_mb, 2),
                    "percent": round(m.percent, 2),
                    "available_mb": round(m.available_mb, 2),
                    "timestamp": m.timestamp.isoformat()
                }
                for m in history
            ]
        }
    except Exception as e:
        logger.error(f"Error getting memory history: {e}")
        raise HTTPException(status_code=500, detail="Memory history collection failed")

@router.post("/memory/gc")
async def force_garbage_collection(current_user: User = Depends(get_current_user)):
    """Force garbage collection - requires authentication"""
    try:
        import gc
        
        # Get memory before GC
        before_metrics = memory_monitor.get_current_metrics()
        
        # Force garbage collection
        collected = gc.collect()
        
        # Get memory after GC
        after_metrics = memory_monitor.get_current_metrics()
        
        return {
            "collected_objects": collected,
            "memory_before_mb": round(before_metrics.rss_mb, 2) if before_metrics else None,
            "memory_after_mb": round(after_metrics.rss_mb, 2) if after_metrics else None,
            "memory_freed_mb": round(before_metrics.rss_mb - after_metrics.rss_mb, 2) if before_metrics and after_metrics else None,
            "timestamp": after_metrics.timestamp.isoformat() if after_metrics else None
        }
        
    except Exception as e:
        logger.error(f"Error during garbage collection: {e}")
        raise HTTPException(status_code=500, detail="Garbage collection failed")

@router.get("/locks/account/{account_id}")
async def get_account_lock_status(
    account_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get lock status for a specific account - requires authentication"""
    try:
        lock_info = await AccountLockManager.get_lock_info(account_id)
        return {
            "account_id": account_id,
            **lock_info
        }
    except Exception as e:
        logger.error(f"Error getting lock status for account {account_id}: {e}")
        raise HTTPException(status_code=500, detail="Lock status check failed")

@router.post("/locks/account/{account_id}/unlock")
async def force_unlock_account(
    account_id: str,
    current_user: User = Depends(get_current_user)
):
    """Force unlock an account (admin operation) - requires authentication"""
    try:
        # Check if user has admin privileges (you may want to add additional checks)
        if not hasattr(current_user, 'app_role') or current_user.app_role != 'admin':
            raise HTTPException(status_code=403, detail="Admin access required")
            
        result = await AccountLockManager.force_unlock_account(account_id)
        return {
            "account_id": account_id,
            "unlocked": result,
            "message": "Account force unlocked successfully" if result else "Failed to unlock account"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error force unlocking account {account_id}: {e}")
        raise HTTPException(status_code=500, detail="Force unlock failed")

@router.get("/locks/status")
async def get_distributed_locks_status(current_user: User = Depends(get_current_user)):
    """Get overview of distributed locking system status - requires authentication"""
    try:
        # Get Redis connection status
        redis_available = redis_manager.is_available() if redis_manager else False
        
        status = {
            "redis_available": redis_available,
            "lock_system_operational": redis_available,
            "fallback_mode": not redis_available,
            "timestamp": memory_monitor.get_current_metrics().timestamp.isoformat() if memory_monitor.get_current_metrics() else None
        }
        
        if redis_available:
            try:
                # Get Redis stats for lock monitoring
                redis_stats = redis_manager.get_stats()
                status["redis_info"] = {
                    "connected_clients": redis_stats.get("connected_clients"),
                    "used_memory_mb": redis_stats.get("used_memory_mb"),
                    "total_connections_received": redis_stats.get("total_connections_received")
                }
            except Exception as e:
                status["redis_info_error"] = str(e)
        
        return status
        
    except Exception as e:
        logger.error(f"Error getting distributed locks status: {e}")
        raise HTTPException(status_code=500, detail="Lock status check failed")

@router.get("/alerts")
async def get_alerts(current_user: User = Depends(get_current_user)):
    """Get active alerts - requires authentication"""
    try:
        active_alerts = await alert_manager.get_active_alerts()
        alert_stats = await alert_manager.get_alert_stats()
        
        return {
            "active_alerts": [
                {
                    "alert_id": alert.alert_id,
                    "alert_type": alert.alert_type.value,
                    "severity": alert.severity.value,
                    "title": alert.title,
                    "message": alert.message,
                    "timestamp": alert.timestamp,
                    "acknowledged": alert.acknowledged,
                    "correlation_id": alert.correlation_id
                }
                for alert in active_alerts
            ],
            "stats": alert_stats
        }
    except Exception as e:
        logger.error(f"Error getting alerts: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve alerts")

@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str, current_user: User = Depends(get_current_user)):
    """Acknowledge an alert - requires authentication"""
    try:
        success = await alert_manager.acknowledge_alert(alert_id, current_user.email or "unknown")
        return {"success": success, "alert_id": alert_id}
    except Exception as e:
        logger.error(f"Error acknowledging alert {alert_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to acknowledge alert")

@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: str, current_user: User = Depends(get_current_user)):
    """Resolve an alert - requires authentication"""
    try:
        success = await alert_manager.resolve_alert(alert_id, current_user.email or "unknown")
        return {"success": success, "alert_id": alert_id}
    except Exception as e:
        logger.error(f"Error resolving alert {alert_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to resolve alert")

@router.get("/circuit-breakers")
async def get_circuit_breakers(current_user: User = Depends(get_current_user)):
    """Get circuit breaker status - requires authentication"""
    try:
        return circuit_breaker_manager.get_all_stats()
    except Exception as e:
        logger.error(f"Error getting circuit breaker status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get circuit breaker status")

@router.post("/circuit-breakers/{circuit_name}/reset")
async def reset_circuit_breaker(circuit_name: str, current_user: User = Depends(get_current_user)):
    """Reset a circuit breaker (admin operation) - requires authentication"""
    try:
        # Check if user has admin privileges
        if not hasattr(current_user, 'app_role') or current_user.app_role != 'admin':
            raise HTTPException(status_code=403, detail="Admin access required")
        
        success = await circuit_breaker_manager.reset_circuit_breaker(circuit_name)
        return {"success": success, "circuit_name": circuit_name}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resetting circuit breaker {circuit_name}: {e}")
        raise HTTPException(status_code=500, detail="Failed to reset circuit breaker")

@router.get("/transactions")
async def get_active_transactions(current_user: User = Depends(get_current_user)):
    """Get active rollback transactions - requires authentication"""
    try:
        return rollback_manager.get_active_transactions()
    except Exception as e:
        logger.error(f"Error getting active transactions: {e}")
        raise HTTPException(status_code=500, detail="Failed to get active transactions")

@router.post("/transactions/{transaction_id}/rollback")
async def force_rollback_transaction(transaction_id: str, current_user: User = Depends(get_current_user)):
    """Force rollback of a transaction (admin operation) - requires authentication"""
    try:
        # Check if user has admin privileges
        if not hasattr(current_user, 'app_role') or current_user.app_role != 'admin':
            raise HTTPException(status_code=403, detail="Admin access required")
        
        success = await rollback_manager.force_rollback(transaction_id)
        return {"success": success, "transaction_id": transaction_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error forcing rollback of transaction {transaction_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to force rollback")

@router.get("/worker")
async def get_worker_status(current_user: User = Depends(get_current_user)):
    """Get worker and shutdown manager status - requires authentication"""
    try:
        return shutdown_manager.get_stats()
    except Exception as e:
        logger.error(f"Error getting worker status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get worker status")