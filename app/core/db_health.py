# app/core/db_health.py
from sqlalchemy import text
from datetime import datetime
import logging
from typing import Dict, Any

from ..db.session import SessionLocal, engine
from ..db.base import init_db  # Import it from base instead

logger = logging.getLogger(__name__)

def check_database_health() -> Dict[str, Any]:
    """Comprehensive database health check"""
    try:
        db = SessionLocal()
        health_status = {
            "status": "healthy",
            "connectivity": True,
            "tables": {},
            "timestamp": datetime.utcnow().isoformat()
        }

        try:
            # Basic connectivity test
            db.execute(text("SELECT 1"))
            logger.info("Database connectivity check passed")

            # Verify essential tables exist and are accessible
            essential_tables = [
                "users", "webhooks", "webhook_logs", "broker_accounts",
                "broker_credentials", "activated_strategies", "subscriptions"
            ]
            
            for table in essential_tables:
                try:
                    db.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))
                    health_status["tables"][table] = "accessible"
                except Exception as table_error:
                    health_status["tables"][table] = "error"
                    logger.error(f"Table check failed for {table}: {str(table_error)}")
                    health_status["status"] = "unhealthy"

            return health_status

        except Exception as e:
            health_status["status"] = "unhealthy"
            health_status["error"] = str(e)
            logger.error(f"Database health check failed: {str(e)}")
            return health_status

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Critical database error: {str(e)}")
        return {
            "status": "critical",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }