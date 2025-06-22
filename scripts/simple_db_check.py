#!/usr/bin/env python3
"""
Simple diagnostic script that only shows database connection configuration
without requiring external packages
"""
import os
import sys
from pathlib import Path

def load_env_file(env_file_path):
    """Load environment variables from a .env file"""
    if os.path.exists(env_file_path):
        print(f"Loading environment from: {env_file_path}")
        with open(env_file_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()
        print("Environment variables loaded.")
        print()

def show_database_config():
    """Show all database configuration without connecting"""
    
    print("=== DATABASE CONNECTION CONFIGURATION ===")
    
    # Show environment variables
    print(f"ENVIRONMENT: {os.getenv('ENVIRONMENT', 'Not set')}")
    print(f"RAILWAY_ENVIRONMENT: {os.getenv('RAILWAY_ENVIRONMENT', 'Not set')}")
    print()
    
    # Show all database-related environment variables
    db_vars = [
        'DATABASE_URL',
        'DEV_DATABASE_URL', 
        'PROD_DATABASE_URL',
        'DATABASE_PRIVATE_URL',
        'PGHOST',
        'PGPORT',
        'PGUSER', 
        'PGPASSWORD',
        'PGDATABASE'
    ]
    
    print("ENVIRONMENT VARIABLES:")
    for var in db_vars:
        value = os.getenv(var, 'Not set')
        if value != 'Not set' and 'PASSWORD' not in var:
            # Show first 70 chars for URLs, hide passwords
            display_value = value[:70] + "..." if len(value) > 70 else value
            print(f"  {var}: {display_value}")
        elif 'PASSWORD' in var and value != 'Not set':
            print(f"  {var}: ***SET*** (hidden)")
        else:
            print(f"  {var}: {value}")
    
    print()
    
    # Try to determine which URL would be used based on logic
    is_on_railway = os.getenv("RAILWAY_ENVIRONMENT") is not None
    
    print("URL SELECTION LOGIC:")
    print(f"  Running on Railway: {is_on_railway}")
    
    if is_on_railway:
        railway_private_url = os.getenv("DATABASE_PRIVATE_URL")
        if railway_private_url:
            print(f"  → Would use DATABASE_PRIVATE_URL: {railway_private_url[:70]}...")
        else:
            print("  → DATABASE_PRIVATE_URL not available, would fall back")
    
    environment = os.getenv('ENVIRONMENT', 'development')
    print(f"  Environment setting: {environment}")
    
    if environment == "production":
        prod_url = os.getenv('PROD_DATABASE_URL')
        if prod_url:
            print(f"  → Would use PROD_DATABASE_URL: {prod_url[:70]}...")
        else:
            print("  → PROD_DATABASE_URL not set, would fall back")
    elif environment == "development":
        dev_url = os.getenv('DEV_DATABASE_URL')
        if dev_url:
            print(f"  → Would use DEV_DATABASE_URL: {dev_url[:70]}...")
        else:
            print("  → DEV_DATABASE_URL not set, would fall back")
    
    database_url = os.getenv('DATABASE_URL')
    if database_url:
        print(f"  → Final fallback DATABASE_URL: {database_url[:70]}...")
    else:
        print("  → No DATABASE_URL fallback available")

if __name__ == "__main__":
    # Try to load environment from .env.diagnostic file
    env_file = Path(__file__).parent.parent / ".env.diagnostic"
    load_env_file(env_file)
    
    show_database_config()