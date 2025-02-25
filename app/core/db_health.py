# app/core/db_health.py
import logging
from typing import Dict, Any
from sqlalchemy import text, inspect
import time
import asyncio
from app.db.session import engine, get_db_context
from app.core.config import settings

logger = logging.getLogger(__name__)

async def check_database_health() -> Dict[str, Any]:
    """
    Comprehensive database health check with detailed diagnostics
    """
    start_time = time.time()
    result = {
        "status": "unknown",
        "environment": settings.ENVIRONMENT,
        "connection": False,
        "tables_exist": False,
        "query_response_time_ms": None,
        "table_count": 0,
        "message": "",
        "details": {}
    }
    
    try:
        # Step 1: Check basic connection
        if engine is None:
            result["status"] = "critical"
            result["message"] = "Database engine not initialized"
            return result
        
        # Step 2: Verify connection and measure response time
        logger.debug("Testing database connection...")
        try:
            with get_db_context() as db:
                query_start = time.time()
                db.execute(text("SELECT 1"))
                query_time = time.time() - query_start
                
                result["connection"] = True
                result["query_response_time_ms"] = round(query_time * 1000, 2)
                
                # Step 3: Check if tables exist
                inspector = inspect(engine)
                tables = inspector.get_table_names()
                result["table_count"] = len(tables)
                result["tables_exist"] = len(tables) > 0
                
                # Get additional diagnostics in development mode
                if settings.ENVIRONMENT != "production":
                    # Table details
                    result["details"]["tables"] = tables
                    
                    # Connection pool stats
                    pool_stats = {
                        "pool_size": engine.pool.size(),
                        "checkedin": engine.pool.checkedin(),
                        "overflow": engine.pool.overflow(),
                        "checkedout": engine.pool.checkedout(),
                    }
                    result["details"]["connection_pool"] = pool_stats
                
                # Determine overall status
                if result["query_response_time_ms"] < 100:
                    status = "healthy"
                elif result["query_response_time_ms"] < 500:
                    status = "degraded"
                else:
                    status = "slow"
                    
                result["status"] = status
                result["message"] = f"Database connection {status} ({result['query_response_time_ms']}ms)"
                
        except Exception as conn_error:
            result["status"] = "critical"
            result["message"] = f"Database query failed: {str(conn_error)}"
            logger.error(f"Database health check query error: {str(conn_error)}")
    
    except Exception as e:
        result["status"] = "error"
        result["message"] = f"Health check failed: {str(e)}"
        logger.error(f"Database health check failed: {str(e)}")
    
    # Calculate total check time
    result["check_duration_ms"] = round((time.time() - start_time) * 1000, 2)
    
    # Log results based on environment
    if settings.ENVIRONMENT == "development" or result["status"] not in ["healthy", "degraded"]:
        logger.info(f"Database health: {result['status']} - {result['message']}")
    
    return result

async def verify_database_schema(required_tables=None) -> Dict[str, Any]:
    """
    Verify database schema against expected tables
    """
    if required_tables is None:
        # Default required tables
        required_tables = [
            "users", "webhooks", "webhook_logs", "broker_accounts", 
            "broker_credentials", "subscriptions", "activated_strategies"
        ]
    
    result = {
        "schema_valid": False,
        "missing_tables": [],
        "environment": settings.ENVIRONMENT,
        "details": {}
    }
    
    try:
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()
        
        missing = [table for table in required_tables if table not in existing_tables]
        result["missing_tables"] = missing
        result["schema_valid"] = len(missing) == 0
        
        # In development, provide more details
        if settings.ENVIRONMENT != "production":
            result["details"]["existing_tables"] = existing_tables
            
            # Get column info for existing required tables
            table_schemas = {}
            for table in required_tables:
                if table in existing_tables:
                    columns = inspector.get_columns(table)
                    table_schemas[table] = [
                        {"name": col["name"], "type": str(col["type"])} 
                        for col in columns
                    ]
            
            result["details"]["table_schemas"] = table_schemas
    
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Schema verification error: {str(e)}")
    
    return result

async def run_health_check() -> Dict[str, Any]:
    """
    Run a comprehensive health check for the database
    """
    health = await check_database_health()
    schema = await verify_database_schema() if health["connection"] else {"schema_valid": False}
    
    return {
        "database": {
            "health": health,
            "schema": schema
        },
        "environment": settings.ENVIRONMENT,
        "timestamp": time.time()
    }

# Don't call this as a side effect - it should be explicitly called
if __name__ == "__main__":
    # Simple way to test this module directly
    asyncio.run(run_health_check())