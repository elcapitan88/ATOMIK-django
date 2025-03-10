from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from datetime import datetime, timedelta
import logging
import psutil
import os
import platform
import sys
import socket

from app.db.session import get_db, test_db_connection
from app.models.user import User
from app.core.security import get_current_user
from app.core.permissions import admin_required
from app.core.db_health import check_database_health
from app.core.config import settings
from app.websockets.manager import websocket_manager

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/health", response_model=Dict[str, Any])
async def get_system_health(
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_required),
):
    """Get system health metrics"""
    try:
        # Get database health
        db_health = await check_database_health()
        
        # Get CPU info
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()
        
        # Get memory info
        memory = psutil.virtual_memory()
        memory_total = memory.total
        memory_available = memory.available
        memory_used = memory.used
        memory_percent = memory.percent
        
        # Get disk info
        disk = psutil.disk_usage('/')
        disk_total = disk.total
        disk_used = disk.used
        disk_free = disk.free
        disk_percent = disk.percent
        
        # Get process info
        process = psutil.Process(os.getpid())
        process_memory = process.memory_info().rss
        process_cpu = process.cpu_percent(interval=1)
        process_threads = process.num_threads()
        process_open_files = len(process.open_files())
        
        # Get websocket stats
        ws_stats = websocket_manager.get_stats()
        
        # Get system info
        hostname = socket.gethostname()
        ip_address = socket.gethostbyname(hostname)
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": {
                "hostname": hostname,
                "platform": platform.platform(),
                "python_version": sys.version,
                "ip_address": ip_address,
                "uptime": psutil.boot_time()
            },
            "resources": {
                "cpu": {
                    "percent": cpu_percent,
                    "count": cpu_count
                },
                "memory": {
                    "total": memory_total,
                    "available": memory_available,
                    "used": memory_used,
                    "percent": memory_percent
                },
                "disk": {
                    "total": disk_total,
                    "used": disk_used,
                    "free": disk_free,
                    "percent": disk_percent
                }
            },
            "process": {
                "memory": process_memory,
                "cpu_percent": process_cpu,
                "threads": process_threads,
                "open_files": process_open_files
            },
            "database": db_health,
            "websockets": ws_stats,
            "environment": settings.ENVIRONMENT
        }
        
    except Exception as e:
        logger.error(f"Error fetching system health: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch system health: {str(e)}"
        )

@router.get("/error-log", response_model=Dict[str, Any])
async def get_error_log(
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_required),
    limit: int = 100
):
    """Get recent application error logs"""
    try:
        # This is a placeholder - you would need to implement
        # error log reading based on your logging configuration
        # Here we're assuming log files are in a logs directory
        
        log_path = os.environ.get("LOG_FILE_PATH", "logs/app.log")
        
        if not os.path.exists(log_path):
            return {
                "logs": [],
                "message": f"Log file not found at {log_path}"
            }
            
        # Read the last 'limit' lines from the log file
        # This is a simple implementation - in production you might
        # want to use a more sophisticated log reader that can filter by level
        with open(log_path, 'r') as f:
            lines = f.readlines()
            
        # Get only error and higher severity logs
        error_logs = [
            line for line in lines
            if "ERROR" in line or "CRITICAL" in line
        ]
        
        return {
            "logs": error_logs[-limit:] if error_logs else [],
            "total": len(error_logs)
        }
        
    except Exception as e:
        logger.error(f"Error fetching error logs: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch error logs: {str(e)}"
        )