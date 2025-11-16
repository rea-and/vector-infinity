#!/usr/bin/env python3
"""Migration script to add multi-user support to existing database.

This script:
1. Creates the users table if it doesn't exist
2. Adds user_id column to import_logs table
3. Adds user_id column to data_items table
4. Creates a default admin user if no users exist
5. Migrates existing data to the default admin user
"""

import sqlite3
import sys
from pathlib import Path
import config
import logging
from werkzeug.security import generate_password_hash
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate_database():
    """Migrate database to support multi-user."""
    db_path = config.DATABASE_PATH
    
    if not db_path.exists():
        logger.info("Database doesn't exist yet. It will be created on first run.")
        return
    
    logger.info(f"Migrating database at {db_path}")
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    try:
        # Check if users table exists
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='users'
        """)
        users_table_exists = cursor.fetchone() is not None
        
        # Check if user_id columns exist
        cursor.execute("PRAGMA table_info(import_logs)")
        import_logs_columns = [row[1] for row in cursor.fetchall()]
        has_user_id_in_logs = 'user_id' in import_logs_columns
        
        cursor.execute("PRAGMA table_info(data_items)")
        data_items_columns = [row[1] for row in cursor.fetchall()]
        has_user_id_in_items = 'user_id' in data_items_columns
        
        # Step 1: Create users table if it doesn't exist
        if not users_table_exists:
            logger.info("Creating users table...")
            cursor.execute("""
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email VARCHAR(255) NOT NULL UNIQUE,
                    password_hash VARCHAR(255) NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX ix_users_email ON users(email)")
            logger.info("✓ Users table created")
        else:
            logger.info("✓ Users table already exists")
        
        # Step 2: Create default admin user if no users exist
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        
        if user_count == 0:
            logger.info("Creating default admin user...")
            default_email = "admin@vectorinfinity.local"
            default_password = "admin123"  # User should change this!
            password_hash = generate_password_hash(default_password)
            now = datetime.now(timezone.utc).isoformat()
            
            cursor.execute("""
                INSERT INTO users (email, password_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?)
            """, (default_email, password_hash, now, now))
            
            admin_user_id = cursor.lastrowid
            logger.info(f"✓ Default admin user created (ID: {admin_user_id})")
            logger.warning(f"⚠️  Default credentials: {default_email} / {default_password}")
            logger.warning("⚠️  Please change the password after first login!")
        else:
            # Get the first user ID to use for existing data
            cursor.execute("SELECT id FROM users ORDER BY id LIMIT 1")
            admin_user_id = cursor.fetchone()[0]
            logger.info(f"Using existing user ID {admin_user_id} for migration")
        
        # Step 3: Add user_id to import_logs if it doesn't exist
        if not has_user_id_in_logs:
            logger.info("Adding user_id column to import_logs table...")
            cursor.execute("""
                ALTER TABLE import_logs 
                ADD COLUMN user_id INTEGER
            """)
            
            # Set all existing import logs to the admin user
            cursor.execute("""
                UPDATE import_logs 
                SET user_id = ? 
                WHERE user_id IS NULL
            """, (admin_user_id,))
            
            # Make user_id NOT NULL after setting values
            # SQLite doesn't support ALTER COLUMN, so we need to recreate the table
            logger.info("Making user_id NOT NULL in import_logs...")
            cursor.execute("""
                CREATE TABLE import_logs_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    plugin_name VARCHAR(100) NOT NULL,
                    status VARCHAR(20) NOT NULL,
                    started_at DATETIME NOT NULL,
                    completed_at DATETIME,
                    records_imported INTEGER DEFAULT 0,
                    error_message TEXT,
                    log_metadata TEXT,
                    progress_current INTEGER DEFAULT 0,
                    progress_total INTEGER DEFAULT 0,
                    progress_message VARCHAR(500)
                )
            """)
            cursor.execute("""
                INSERT INTO import_logs_new 
                SELECT id, user_id, plugin_name, status, started_at, completed_at,
                       records_imported, error_message, log_metadata,
                       progress_current, progress_total, progress_message
                FROM import_logs
            """)
            cursor.execute("DROP TABLE import_logs")
            cursor.execute("ALTER TABLE import_logs_new RENAME TO import_logs")
            cursor.execute("CREATE INDEX ix_import_logs_user_id ON import_logs(user_id)")
            cursor.execute("CREATE INDEX ix_import_logs_plugin_name ON import_logs(plugin_name)")
            logger.info("✓ user_id column added to import_logs")
        else:
            logger.info("✓ user_id column already exists in import_logs")
        
        # Step 4: Add user_id to data_items if it doesn't exist
        if not has_user_id_in_items:
            logger.info("Adding user_id column to data_items table...")
            cursor.execute("""
                ALTER TABLE data_items 
                ADD COLUMN user_id INTEGER
            """)
            
            # Set all existing data items to the admin user
            cursor.execute("""
                UPDATE data_items 
                SET user_id = ? 
                WHERE user_id IS NULL
            """, (admin_user_id,))
            
            # Make user_id NOT NULL after setting values
            logger.info("Making user_id NOT NULL in data_items...")
            cursor.execute("""
                CREATE TABLE data_items_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    plugin_name VARCHAR(100) NOT NULL,
                    source_id VARCHAR(255) NOT NULL,
                    item_type VARCHAR(50) NOT NULL,
                    title VARCHAR(500),
                    content TEXT,
                    item_metadata TEXT,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    source_timestamp DATETIME,
                    embedding BLOB
                )
            """)
            cursor.execute("""
                INSERT INTO data_items_new 
                SELECT id, user_id, plugin_name, source_id, item_type, title, content,
                       item_metadata, created_at, updated_at, source_timestamp, embedding
                FROM data_items
            """)
            cursor.execute("DROP TABLE data_items")
            cursor.execute("ALTER TABLE data_items_new RENAME TO data_items")
            cursor.execute("CREATE INDEX ix_data_items_user_id ON data_items(user_id)")
            cursor.execute("CREATE INDEX ix_data_items_plugin_name ON data_items(plugin_name)")
            logger.info("✓ user_id column added to data_items")
        else:
            logger.info("✓ user_id column already exists in data_items")
        
        conn.commit()
        logger.info("✓ Database migration completed successfully!")
        
        if user_count == 0:
            logger.info("")
            logger.info("=" * 60)
            logger.info("IMPORTANT: Default admin user created!")
            logger.info(f"Email: {default_email}")
            logger.info(f"Password: {default_password}")
            logger.info("Please change the password after first login!")
            logger.info("=" * 60)
            logger.info("")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Error during migration: {e}", exc_info=True)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        migrate_database()
        sys.exit(0)
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        sys.exit(1)

