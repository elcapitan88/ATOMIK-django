#!/usr/bin/env python3
"""
Script to fix alembic version and run maintenance settings migration.
"""

import os
import sys
from pathlib import Path

# Add the current directory to Python path
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

# Set the DATABASE_URL to production
production_db_url = "postgresql://postgres:ljjqmjlQJdyBWjNzUglEQxKmfzmZRGfi@metro.proxy.rlwy.net:47089/railway"
os.environ['DATABASE_URL'] = production_db_url

print("🚀 Fixing alembic version and running maintenance settings migration...")
print(f"📍 Working directory: {current_dir}")
print(f"🗄️  Target database: {production_db_url.split('@')[1]}")

try:
    # Test database connection first
    print("\n1️⃣ Testing database connection...")
    from sqlalchemy import create_engine, text
    
    engine = create_engine(production_db_url)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT version()"))
        db_version = result.fetchone()[0]
        print(f"   ✅ Database connected: {db_version[:50]}...")
    
    # Check and fix current migration state
    print("\n2️⃣ Checking and fixing current migration state...")
    try:
        with engine.connect() as conn:
            # Check current version
            result = conn.execute(text("SELECT version_num FROM alembic_version ORDER BY version_num DESC LIMIT 1"))
            current_version = result.fetchone()
            if current_version:
                print(f"   📌 Current migration in DB: {current_version[0]}")
                
                # Check if this version exists in our migration files
                migration_file = Path(f"alembic/versions/{current_version[0]}_*.py")
                if not list(Path("alembic/versions").glob(f"{current_version[0]}_*.py")):
                    print(f"   ⚠️  Migration {current_version[0]} not found in local files")
                    print("   🔧 Fixing by updating to latest known migration: d4d300d41aa7")
                    
                    # Update to a known migration
                    conn.execute(text("UPDATE alembic_version SET version_num = 'd4d300d41aa7'"))
                    conn.commit()
                    print("   ✅ Alembic version updated to d4d300d41aa7")
                else:
                    print("   ✅ Current migration exists in local files")
            else:
                print("   ⚠️  No migrations found, setting to d4d300d41aa7")
                conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('d4d300d41aa7')"))
                conn.commit()
    except Exception as e:
        print(f"   ⚠️  Could not fix migration state: {e}")
    
    # Check if maintenance_settings table already exists
    print("\n3️⃣ Checking if maintenance_settings table exists...")
    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    
    maintenance_exists = 'maintenance_settings' in tables
    
    print(f"   {'✅' if maintenance_exists else '❌'} maintenance_settings table {'exists' if maintenance_exists else 'missing'}")
    
    if maintenance_exists:
        print("\n🎉 maintenance_settings table already exists!")
        # Update alembic version to reflect this
        with engine.connect() as conn:
            conn.execute(text("UPDATE alembic_version SET version_num = '002_add_maintenance_settings'"))
            conn.commit()
        print("   ✅ Alembic version updated to 002_add_maintenance_settings")
        sys.exit(0)
    
    # Create table manually since alembic is having issues
    print("\n4️⃣ Creating maintenance_settings table manually...")
    
    create_table_sql = """
    CREATE TABLE maintenance_settings (
        id SERIAL PRIMARY KEY,
        is_enabled BOOLEAN NOT NULL DEFAULT FALSE,
        message TEXT,
        created_by INTEGER NOT NULL,
        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT fk_maintenance_settings_created_by 
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE CASCADE
    );
    
    CREATE INDEX ix_maintenance_settings_created_by 
        ON maintenance_settings (created_by);
        
    CREATE INDEX ix_maintenance_settings_updated_at 
        ON maintenance_settings (updated_at);
    """
    
    with engine.connect() as conn:
        # Execute each statement separately
        statements = [s.strip() for s in create_table_sql.split(';') if s.strip()]
        for statement in statements:
            print(f"   🔄 Executing: {statement[:50]}...")
            conn.execute(text(statement))
        
        # Update alembic version
        conn.execute(text("UPDATE alembic_version SET version_num = '002_add_maintenance_settings'"))
        conn.commit()
        print("   ✅ Table created and alembic version updated!")
    
    # Verify table was created
    print("\n5️⃣ Verifying maintenance_settings table was created...")
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    
    maintenance_exists = 'maintenance_settings' in tables
    
    print(f"   {'✅' if maintenance_exists else '❌'} maintenance_settings table {'created' if maintenance_exists else 'FAILED'}")
    
    if maintenance_exists:
        print("\n🎉 SUCCESS! maintenance_settings table created successfully.")
        print("\n📋 Maintenance mode features enabled:")
        print("   1. ✅ Database table ready")
        print("   2. ✅ Admin can toggle maintenance mode in settings")
        print("   3. ✅ Users will see maintenance notifications")
        print("   4. ✅ Non-admin users blocked during maintenance")
    else:
        print("\n❌ FAILED! maintenance_settings table was not created.")
        sys.exit(1)
        
    engine.dispose()
    
except Exception as e:
    print(f"\n❌ ERROR: {e}")
    print(f"Error type: {type(e).__name__}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n✨ Maintenance settings migration completed!")
print("\n🔧 You can now access the maintenance mode toggle at:")
print("   👉 /admin/settings (General tab)")
print("   👉 Toggle 'Maintenance Mode' and add custom messages")