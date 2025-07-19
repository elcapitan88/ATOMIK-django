#!/usr/bin/env python3
"""
Fix script for dunning_stage enum issue
Updates any NULL or invalid dunning_stage values to 'none'
"""
import sys
sys.path.append('.')

from app.database import SessionLocal
from sqlalchemy import text

def fix_dunning_stage_values():
    """Fix any NULL or invalid dunning_stage values"""
    db = SessionLocal()
    try:
        # Check current state
        result = db.execute(text("SELECT COUNT(*) FROM subscriptions WHERE dunning_stage IS NULL"))
        null_count = result.scalar()
        print(f"Found {null_count} records with NULL dunning_stage")
        
        # Update NULL values to 'none'
        if null_count > 0:
            db.execute(text("UPDATE subscriptions SET dunning_stage = 'none' WHERE dunning_stage IS NULL"))
            db.commit()
            print(f"✅ Updated {null_count} records to 'none'")
        
        # Check for any invalid enum values
        result = db.execute(text("""
            SELECT COUNT(*) FROM subscriptions 
            WHERE dunning_stage NOT IN ('none', 'warning', 'urgent', 'final', 'suspended')
        """))
        invalid_count = result.scalar()
        
        if invalid_count > 0:
            print(f"Found {invalid_count} records with invalid dunning_stage values")
            # Update invalid values to 'none'
            db.execute(text("""
                UPDATE subscriptions 
                SET dunning_stage = 'none' 
                WHERE dunning_stage NOT IN ('none', 'warning', 'urgent', 'final', 'suspended')
            """))
            db.commit()
            print(f"✅ Fixed {invalid_count} invalid records")
        
        # Verify final state
        result = db.execute(text("SELECT DISTINCT dunning_stage FROM subscriptions ORDER BY dunning_stage"))
        values = [row[0] for row in result.fetchall()]
        print(f"Final dunning_stage values: {values}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
        return False
    finally:
        db.close()
    
    return True

if __name__ == "__main__":
    print("🔧 Fixing dunning_stage enum values...")
    if fix_dunning_stage_values():
        print("✅ Fix completed successfully")
    else:
        print("❌ Fix failed")