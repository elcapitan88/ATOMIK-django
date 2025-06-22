#!/usr/bin/env python3
"""
Diagnostic script to check what database the application is connecting to
and what columns it sees in the affiliates table
"""
import os
import sys
from pathlib import Path

# Add the parent directory to the path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import settings
from sqlalchemy import create_engine, text
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def diagnose_connection():
    """Diagnose the database connection and schema"""
    
    # Get all possible database URLs
    logger.info("=== DATABASE CONNECTION DIAGNOSIS ===")
    
    # Show environment
    logger.info(f"ENVIRONMENT: {settings.ENVIRONMENT}")
    logger.info(f"RAILWAY_ENVIRONMENT: {os.getenv('RAILWAY_ENVIRONMENT', 'Not set')}")
    
    # Show all database URL options
    logger.info(f"DATABASE_URL: {getattr(settings, 'DATABASE_URL', 'Not set')[:50]}...")
    logger.info(f"DEV_DATABASE_URL: {getattr(settings, 'DEV_DATABASE_URL', 'Not set')[:50]}...")
    logger.info(f"PROD_DATABASE_URL: {getattr(settings, 'PROD_DATABASE_URL', 'Not set')[:50]}...")
    logger.info(f"DATABASE_PRIVATE_URL: {os.getenv('DATABASE_PRIVATE_URL', 'Not set')[:50]}...")
    
    # Show the active URL being used
    active_url = settings.active_database_url
    logger.info(f"ACTIVE DATABASE URL: {active_url[:70]}...")
    
    try:
        # Connect to the database
        engine = create_engine(active_url)
        
        with engine.connect() as conn:
            # Get current database name
            result = conn.execute(text("SELECT current_database()")).fetchone()
            current_db = result[0] if result else "Unknown"
            logger.info(f"CONNECTED TO DATABASE: {current_db}")
            
            # Check if affiliates table exists
            result = conn.execute(text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_name = 'affiliates'
            """)).fetchone()
            
            if result:
                logger.info("✅ affiliates table exists")
                
                # Get all columns in affiliates table
                result = conn.execute(text("""
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns 
                    WHERE table_name = 'affiliates'
                    ORDER BY ordinal_position
                """)).fetchall()
                
                logger.info("AFFILIATES TABLE COLUMNS:")
                for row in result:
                    logger.info(f"  - {row[0]} ({row[1]}, nullable: {row[2]})")
                
                # Specifically check for payout columns
                payout_columns = [row for row in result if row[0] in ['payout_method', 'payout_details']]
                if payout_columns:
                    logger.info("✅ PAYOUT COLUMNS FOUND:")
                    for col in payout_columns:
                        logger.info(f"  ✅ {col[0]} ({col[1]})")
                else:
                    logger.error("❌ PAYOUT COLUMNS NOT FOUND!")
                
                # Check alembic version
                try:
                    result = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
                    if result:
                        logger.info(f"ALEMBIC VERSION: {result[0]}")
                    else:
                        logger.warning("No alembic version found")
                except Exception as e:
                    logger.warning(f"Could not read alembic version: {e}")
                
            else:
                logger.error("❌ affiliates table does not exist!")
                
                # Show what tables do exist
                result = conn.execute(text("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public'
                    ORDER BY table_name
                """)).fetchall()
                
                logger.info("EXISTING TABLES:")
                for row in result:
                    logger.info(f"  - {row[0]}")
                
    except Exception as e:
        logger.error(f"❌ CONNECTION ERROR: {e}")

if __name__ == "__main__":
    diagnose_connection()