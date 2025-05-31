#!/usr/bin/env python3
"""
Simple script to initialize chat channels
"""

import os
import sys
import sqlite3
from datetime import datetime

# Check if we have access to the database
db_url = os.environ.get('DATABASE_URL', 'sqlite:///./atomik.db')

def init_chat_channels():
    """Initialize default chat channels in the database"""
    
    if 'sqlite' in db_url:
        # Handle SQLite database
        db_file = db_url.replace('sqlite:///', './').replace('sqlite:///', '')
        if not os.path.exists(db_file):
            print(f"Database file not found: {db_file}")
            print("Please make sure the database is created first by running the migrations.")
            return
            
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        try:
            # Check if chat_channels table exists
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='chat_channels'
            """)
            
            if not cursor.fetchone():
                print("❌ Chat tables not found. Please run the database migration first:")
                print("   alembic upgrade head")
                return
            
            # Default channels to create
            default_channels = [
                ("general", "General discussion for all members", True, 1),
                ("trading-signals", "Trading signals and market discussion", False, 2),
                ("strategy-discussion", "Discuss trading strategies", False, 3),
                ("announcements", "Important platform announcements", False, 4)
            ]
            
            created_count = 0
            for name, description, is_general, sort_order in default_channels:
                # Check if channel already exists
                cursor.execute("SELECT id FROM chat_channels WHERE name = ?", (name,))
                if cursor.fetchone():
                    print(f"  ⏭️  Channel '{name}' already exists")
                    continue
                    
                # Create the channel
                cursor.execute("""
                    INSERT INTO chat_channels (name, description, is_general, sort_order, created_at, updated_at, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (name, description, is_general, sort_order, datetime.utcnow(), datetime.utcnow(), True))
                
                print(f"  ✅ Created channel: #{name}")
                created_count += 1
            
            conn.commit()
            
            if created_count > 0:
                print(f"\n🎉 Successfully created {created_count} chat channels!")
            else:
                print("\n✅ All channels already exist!")
                
            print("\nAvailable channels:")
            cursor.execute("SELECT name, description FROM chat_channels WHERE is_active = 1 ORDER BY sort_order")
            for row in cursor.fetchall():
                print(f"  - #{row[0]}: {row[1]}")
                
        except Exception as e:
            print(f"❌ Error: {e}")
            conn.rollback()
            
        finally:
            conn.close()
    else:
        print("This script currently only supports SQLite databases.")
        print("For PostgreSQL, please use the main setup_chat.py script with proper environment setup.")

if __name__ == "__main__":
    print("🚀 Initializing chat channels...")
    init_chat_channels()