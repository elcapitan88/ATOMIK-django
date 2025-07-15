#!/usr/bin/env python3
"""
Script to run Alembic migration for trades tables to production database.
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

print("🚀 Starting migration process...")
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
    
    # Check if trades tables already exist
    print("\n3️⃣ Checking if trades tables exist...")
    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    
    trades_exists = 'trades' in tables
    executions_exists = 'trade_executions' in tables
    
    print(f"   {'✅' if trades_exists else '❌'} trades table {'exists' if trades_exists else 'missing'}")
    print(f"   {'✅' if executions_exists else '❌'} trade_executions table {'exists' if executions_exists else 'missing'}")
    
    if trades_exists and executions_exists:
        print("\n🎉 Tables already exist! Migration may have been run already.")
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
        
        # Run upgrade to the trades migration
        print("   🔄 Upgrading to migration: 001a2b3c4d5e")
        command.upgrade(alembic_cfg, "001a2b3c4d5e")
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
        command.upgrade(alembic_cfg, "001a2b3c4d5e")
        print("   ✅ Migration completed successfully!")
    
    # Verify tables were created
    print("\n5️⃣ Verifying tables were created...")
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    
    trades_exists = 'trades' in tables
    executions_exists = 'trade_executions' in tables
    
    print(f"   {'✅' if trades_exists else '❌'} trades table {'created' if trades_exists else 'FAILED'}")
    print(f"   {'✅' if executions_exists else '❌'} trade_executions table {'created' if executions_exists else 'FAILED'}")
    
    if trades_exists and executions_exists:
        print("\n🎉 SUCCESS! Both tables created successfully.")
        print("\n📋 Next steps:")
        print("   1. ✅ Database foundation complete")
        print("   2. 🔄 Continue with Phase 1.3: Trade Service Layer")
        print("   3. 🔄 Then Phase 2: WebSocket Integration")
    else:
        print("\n❌ FAILED! Some tables were not created.")
        sys.exit(1)
        
    engine.dispose()
    
except Exception as e:
    print(f"\n❌ ERROR: {e}")
    print(f"Error type: {type(e).__name__}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n✨ Migration process completed!")