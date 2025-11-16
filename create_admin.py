#!/usr/bin/env python3
"""Command-line script to create an admin user.

Usage:
    python3 create_admin.py <email> <password>
    
Note: Make sure to activate the virtual environment first:
    source venv/bin/activate
    python3 create_admin.py <email> <password>
"""

import sys
import os
import logging

# Add the script's directory to the path so we can import modules
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

try:
    from werkzeug.security import generate_password_hash
    from database import User, SessionLocal, init_db
    from datetime import datetime, timezone
except ImportError as e:
    print(f"Error: Missing required dependencies. Please activate the virtual environment first:")
    print(f"  source venv/bin/activate")
    print(f"  python3 create_admin.py <email> <password>")
    print(f"")
    print(f"Import error: {e}")
    sys.exit(1)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_admin(email, password):
    """Create an admin user."""
    # Initialize database
    init_db()
    
    db = SessionLocal()
    try:
        # Check if user already exists
        existing_user = db.query(User).filter_by(email=email).first()
        if existing_user:
            print(f"Error: User with email {email} already exists.")
            print(f"  Role: {existing_user.role}")
            print(f"  Active: {existing_user.is_active()}")
            sys.exit(1)
        
        # Create admin user
        password_hash = generate_password_hash(password)
        admin_user = User(
            email=email,
            password_hash=password_hash,
            role="admin",
            active=1  # Admin accounts are active by default
        )
        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)
        
        print("=" * 60)
        print("Admin user created successfully!")
        print("=" * 60)
        print(f"Email: {email}")
        print(f"Role: admin")
        print(f"Active: Yes")
        print(f"User ID: {admin_user.id}")
        print("=" * 60)
        print("")
        print("You can now log in with these credentials.")
        
        logger.info(f"Admin user created: {email} (ID: {admin_user.id})")
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating admin user: {e}", exc_info=True)
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 create_admin.py <email> <password>")
        print("")
        print("Example:")
        print("  python3 create_admin.py admin@example.com mypassword123")
        sys.exit(1)
    
    email = sys.argv[1].strip().lower()
    password = sys.argv[2]
    
    if not email or not password:
        print("Error: Email and password are required")
        sys.exit(1)
    
    if len(password) < 8:
        print("Error: Password must be at least 8 characters long")
        sys.exit(1)
    
    create_admin(email, password)

