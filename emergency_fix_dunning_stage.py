#!/usr/bin/env python3
"""
Emergency fix for dunning_stage enum issue
This script directly fixes the database enum values to work with SQLAlchemy
"""
import os
import sys
import psycopg2
from psycopg2.extras import RealDictCursor

def get_database_url():
    """Get database URL from environment"""
    # Try different environment variable names
    database_url = (
        os.getenv('DEV_DATABASE_URL') or 
        os.getenv('DATABASE_URL') or
        os.getenv('DB_URL')
    )
    
    if not database_url:
        print("❌ No database URL found in environment variables")
        sys.exit(1)
    
    return database_url

def fix_dunning_stage_enum():
    """Fix dunning_stage enum values directly in PostgreSQL"""
    database_url = get_database_url()
    
    try:
        # Connect to database
        conn = psycopg2.connect(database_url)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        print("🔍 Checking current dunning_stage values...")
        
        # Check current values
        cur.execute("SELECT DISTINCT dunning_stage FROM subscriptions")
        current_values = cur.fetchall()
        print(f"Current values: {[row['dunning_stage'] for row in current_values]}")
        
        # Check for NULL or empty values
        cur.execute("SELECT COUNT(*) FROM subscriptions WHERE dunning_stage IS NULL OR dunning_stage = ''")
        null_count = cur.fetchone()['count']
        print(f"NULL/empty values: {null_count}")
        
        if null_count > 0:
            print("🔧 Fixing NULL/empty values...")
            cur.execute("UPDATE subscriptions SET dunning_stage = 'none' WHERE dunning_stage IS NULL OR dunning_stage = ''")
            print(f"✅ Updated {null_count} records")
        
        # Check if enum type exists and values
        cur.execute("""
            SELECT enumlabel 
            FROM pg_enum 
            WHERE enumtypid = (
                SELECT oid FROM pg_type WHERE typname = 'dunningstage'
            )
            ORDER BY enumsortorder
        """)
        enum_values = cur.fetchall()
        
        if enum_values:
            print(f"✅ Enum 'dunningstage' exists with values: {[row['enumlabel'] for row in enum_values]}")
        else:
            print("❌ Enum 'dunningstage' not found - creating it...")
            cur.execute("CREATE TYPE dunningstage AS ENUM ('none', 'warning', 'urgent', 'final', 'suspended')")
            print("✅ Created enum type")
        
        # Ensure all subscription records have valid enum values
        cur.execute("""
            UPDATE subscriptions 
            SET dunning_stage = 'none' 
            WHERE dunning_stage NOT IN ('none', 'warning', 'urgent', 'final', 'suspended')
        """)
        
        # Commit changes
        conn.commit()
        
        # Verify final state
        cur.execute("SELECT DISTINCT dunning_stage FROM subscriptions ORDER BY dunning_stage")
        final_values = cur.fetchall()
        print(f"✅ Final dunning_stage values: {[row['dunning_stage'] for row in final_values]}")
        
        cur.close()
        conn.close()
        
        print("✅ Database fix completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        return False

if __name__ == "__main__":
    print("🚨 Emergency Fix: Dunning Stage Enum Issue")
    print("=" * 50)
    
    if fix_dunning_stage_enum():
        print("\n🎉 Fix completed! Try logging in again.")
    else:
        print("\n💥 Fix failed. Manual intervention required.")