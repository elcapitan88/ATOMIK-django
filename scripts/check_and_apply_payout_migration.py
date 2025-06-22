#!/usr/bin/env python3
"""
Script to check and apply the payout management migration to production database
"""
import os
import sys
from pathlib import Path
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.exc import ProgrammingError
import logging

# Add the parent directory to the path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import settings

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def check_migration_status(engine):
    """Check if the payout columns exist and if the migration was applied"""
    inspector = inspect(engine)
    
    # Check if affiliates table exists
    if 'affiliates' not in inspector.get_table_names():
        logger.error("❌ affiliates table does not exist!")
        return False, False, None
    
    # Check for payout columns
    columns = [col['name'] for col in inspector.get_columns('affiliates')]
    has_payout_method = 'payout_method' in columns
    has_payout_details = 'payout_details' in columns
    
    logger.info(f"📊 Affiliates table columns: {', '.join(columns)}")
    logger.info(f"✓ payout_method exists: {has_payout_method}")
    logger.info(f"✓ payout_details exists: {has_payout_details}")
    
    # Check alembic version
    try:
        result = engine.execute(text("SELECT version_num FROM alembic_version")).fetchone()
        current_version = result[0] if result else None
        logger.info(f"📌 Current alembic version: {current_version}")
        return has_payout_method, has_payout_details, current_version
    except Exception as e:
        logger.warning(f"⚠️  Could not read alembic version: {e}")
        return has_payout_method, has_payout_details, None

def apply_migration_manually(engine):
    """Apply the payout migration manually if alembic is out of sync"""
    try:
        with engine.begin() as conn:
            # Check if columns already exist
            inspector = inspect(engine)
            columns = [col['name'] for col in inspector.get_columns('affiliates')]
            
            # Add payout_method column if missing
            if 'payout_method' not in columns:
                logger.info("📝 Adding payout_method column...")
                conn.execute(text("ALTER TABLE affiliates ADD COLUMN payout_method VARCHAR"))
                logger.info("✅ payout_method column added")
            
            # Add payout_details column if missing
            if 'payout_details' not in columns:
                logger.info("📝 Adding payout_details column...")
                conn.execute(text("ALTER TABLE affiliates ADD COLUMN payout_details JSON"))
                logger.info("✅ payout_details column added")
            
            # Check if affiliate_payouts table exists
            if 'affiliate_payouts' not in inspector.get_table_names():
                logger.info("📝 Creating affiliate_payouts table...")
                conn.execute(text("""
                    CREATE TABLE affiliate_payouts (
                        id SERIAL PRIMARY KEY,
                        affiliate_id INTEGER NOT NULL REFERENCES affiliates(id) ON DELETE CASCADE,
                        payout_amount FLOAT NOT NULL,
                        payout_method VARCHAR NOT NULL,
                        payout_details JSON,
                        period_start TIMESTAMP NOT NULL,
                        period_end TIMESTAMP NOT NULL,
                        status VARCHAR DEFAULT 'pending' NOT NULL,
                        payout_date TIMESTAMP,
                        transaction_id VARCHAR,
                        currency VARCHAR DEFAULT 'USD' NOT NULL,
                        commission_count INTEGER DEFAULT 0 NOT NULL,
                        notes TEXT,
                        created_at TIMESTAMP DEFAULT NOW() NOT NULL,
                        updated_at TIMESTAMP DEFAULT NOW() NOT NULL
                    )
                """))
                
                # Create indexes
                conn.execute(text("CREATE INDEX ix_affiliate_payouts_id ON affiliate_payouts(id)"))
                conn.execute(text("CREATE INDEX ix_affiliate_payouts_affiliate_id ON affiliate_payouts(affiliate_id)"))
                conn.execute(text("CREATE INDEX ix_affiliate_payouts_status ON affiliate_payouts(status)"))
                conn.execute(text("CREATE INDEX ix_affiliate_payouts_period_end ON affiliate_payouts(period_end)"))
                conn.execute(text("CREATE INDEX ix_affiliate_payouts_payout_date ON affiliate_payouts(payout_date)"))
                
                logger.info("✅ affiliate_payouts table created with indexes")
            
            # Update alembic version if needed
            try:
                conn.execute(text("UPDATE alembic_version SET version_num = 'jkl345mno678'"))
                logger.info("✅ Updated alembic version to jkl345mno678")
            except Exception as e:
                logger.warning(f"⚠️  Could not update alembic version: {e}")
            
            return True
            
    except Exception as e:
        logger.error(f"❌ Error applying migration: {e}")
        return False

def main():
    """Main function to check and apply migration"""
    # Get the production database URL
    db_url = settings.active_database_url
    logger.info(f"🔗 Connecting to database: {db_url[:50]}...")
    
    try:
        # Create engine
        engine = create_engine(db_url)
        
        # Check current status
        has_payout_method, has_payout_details, current_version = check_migration_status(engine)
        
        if has_payout_method and has_payout_details:
            logger.info("✅ All payout columns already exist!")
            return
        
        # Apply migration
        logger.info("🚀 Applying payout management migration...")
        if apply_migration_manually(engine):
            logger.info("✅ Migration completed successfully!")
            
            # Verify the changes
            has_payout_method, has_payout_details, current_version = check_migration_status(engine)
            if has_payout_method and has_payout_details:
                logger.info("✅ Verification passed - all columns now exist!")
            else:
                logger.error("❌ Verification failed - columns still missing")
        else:
            logger.error("❌ Migration failed!")
            
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        raise

if __name__ == "__main__":
    main()