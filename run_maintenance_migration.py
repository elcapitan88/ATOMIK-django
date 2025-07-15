#!/usr/bin/env python3
"""
Script to run Alembic migration for maintenance settings table.
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

print("🚀 Starting maintenance settings migration process...")
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
    
    # Check current migration state
    print("\n2️⃣ Checking current migration state...")
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version_num FROM alembic_version ORDER BY version_num DESC LIMIT 1"))
            current_version = result.fetchone()
            if current_version:
                print(f"   📌 Current migration: {current_version[0]}")
            else:
                print("   ⚠️  No migrations found in alembic_version table")
    except Exception as e:
        print(f"   ⚠️  Could not read migration state: {e}")
    
    # Check if maintenance_settings table already exists
    print("\n3️⃣ Checking if maintenance_settings table exists...")
    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    
    maintenance_exists = 'maintenance_settings' in tables
    
    print(f"   {'✅' if maintenance_exists else '❌'} maintenance_settings table {'exists' if maintenance_exists else 'missing'}")
    
    if maintenance_exists:
        print("\n🎉 maintenance_settings table already exists! Migration may have been run already.")
        sys.exit(0)
    
    # Run the migration
    print("\n4️⃣ Running Alembic migration...")
    
    # Import alembic components
    try:
        from alembic.config import Config
        from alembic import command
        
        # Create alembic config
        alembic_cfg = Config("alembic.ini")
        
        # Override the database URL in the config
        alembic_cfg.set_main_option("sqlalchemy.url", production_db_url)
        
        # Run upgrade to the maintenance settings migration
        print("   🔄 Upgrading to migration: 002_add_maintenance_settings")
        command.upgrade(alembic_cfg, "002_add_maintenance_settings")
        print("   ✅ Migration completed successfully!")
        
    except ImportError:
        print("   ❌ Alembic not available. Installing dependencies...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "alembic"])
        
        # Try again after installation
        from alembic.config import Config
        from alembic import command
        
        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", production_db_url)
        command.upgrade(alembic_cfg, "002_add_maintenance_settings")
        print("   ✅ Migration completed successfully!")
    
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