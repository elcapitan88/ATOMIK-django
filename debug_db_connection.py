#!/usr/bin/env python3
"""
Debug script to check database connection and URL parsing
"""
import os
from urllib.parse import urlparse, quote_plus
from app.core.config import settings

def debug_database_url():
    """Debug database URL parsing and connection"""
    print("=== Database Connection Debug ===")
    
    # Get DATABASE_URL from different sources
    env_db_url = os.getenv('DATABASE_URL')
    settings_db_url = settings.DATABASE_URL
    
    print(f"Environment DATABASE_URL: {env_db_url}")
    print(f"Settings DATABASE_URL: {settings_db_url}")
    
    if settings_db_url:
        # Parse URL to check components
        parsed = urlparse(settings_db_url)
        print(f"\nParsed URL components:")
        print(f"  Scheme: {parsed.scheme}")
        print(f"  Username: {parsed.username}")
        print(f"  Password: {'*' * len(parsed.password) if parsed.password else 'None'}")
        print(f"  Hostname: {parsed.hostname}")
        print(f"  Port: {parsed.port}")
        print(f"  Database: {parsed.path.lstrip('/')}")
        
        # Check if password contains special characters that need encoding
        if parsed.password:
            original_password = parsed.password
            encoded_password = quote_plus(original_password)
            print(f"\nPassword encoding check:")
            print(f"  Original password: {original_password}")
            print(f"  URL encoded password: {encoded_password}")
            print(f"  Encoding needed: {original_password != encoded_password}")
            
            if original_password != encoded_password:
                # Show what the corrected URL would look like
                corrected_url = settings_db_url.replace(original_password, encoded_password)
                print(f"  Corrected URL: {corrected_url}")
    
    # Test actual connection
    print(f"\n=== Testing Database Connection ===")
    try:
        from app.db.session import engine
        from sqlalchemy import text
        if engine:
            with engine.connect() as conn:
                result = conn.execute(text("SELECT 1"))
                print("SUCCESS: Database connection successful!")
        else:
            print("ERROR: Engine is None - connection failed during setup")
    except Exception as e:
        print(f"ERROR: Database connection failed: {str(e)}")
        print(f"   Error type: {type(e).__name__}")

if __name__ == "__main__":
    debug_database_url()