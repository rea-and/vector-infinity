#!/usr/bin/env python3
"""Migration script to add assistant_model column to user_settings table."""
import sqlite3
import sys
from pathlib import Path
import config

def migrate():
    """Add assistant_model column to user_settings table if it doesn't exist."""
    db_path = config.DATABASE_PATH
    
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        print("Database will be created automatically on first run.")
        return
    
    print(f"Connecting to database: {db_path}")
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    try:
        # Check if table exists
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='user_settings'
        """)
        table_exists = cursor.fetchone() is not None
        
        if not table_exists:
            print("Table 'user_settings' does not exist yet.")
            print("The table will be created automatically with the new column on first run.")
            return
        
        # Check if column already exists
        cursor.execute("PRAGMA table_info(user_settings)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'assistant_model' in columns:
            print("Column 'assistant_model' already exists. Migration not needed.")
            return
        
        print("Adding 'assistant_model' column to user_settings table...")
        cursor.execute("""
            ALTER TABLE user_settings 
            ADD COLUMN assistant_model VARCHAR(50)
        """)
        
        conn.commit()
        print("✓ Successfully added 'assistant_model' column to user_settings table.")
        
    except sqlite3.Error as e:
        conn.rollback()
        print(f"✗ Error during migration: {e}")
        sys.exit(1)
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()

