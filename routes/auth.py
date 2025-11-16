"""Authentication routes."""
from flask import Blueprint, request, jsonify, render_template_string, redirect, url_for
from flask_login import login_user, logout_user, login_required, current_user
import logging
from database import User, SessionLocal
from werkzeug.security import generate_password_hash, check_password_hash
import re

logger = logging.getLogger(__name__)

bp = Blueprint('auth', __name__, url_prefix='/api/auth')


def validate_email(email):
    """Validate email format."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


def validate_password(password):
    """Validate password strength."""
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    return True, None


@bp.route("/register", methods=["POST"])
def register():
    """Register a new user."""
    try:
        data = request.get_json() or {}
        email = data.get("email", "").strip().lower()
        password = data.get("password", "")
        
        if not email or not password:
            return jsonify({"error": "Email and password are required"}), 400
        
        # Validate email format
        if not validate_email(email):
            return jsonify({"error": "Invalid email format"}), 400
        
        # Validate password
        is_valid, error_msg = validate_password(password)
        if not is_valid:
            return jsonify({"error": error_msg}), 400
        
        db = SessionLocal()
        try:
            # Check if user already exists
            existing_user = db.query(User).filter_by(email=email).first()
            if existing_user:
                return jsonify({"error": "User with this email already exists"}), 400
            
            # Create new user (regular user, inactive by default)
            password_hash = generate_password_hash(password)
            new_user = User(
                email=email,
                password_hash=password_hash,
                role="regular",
                active=0  # Inactive until admin approves
            )
            db.add(new_user)
            db.commit()
            db.refresh(new_user)
            
            logger.info(f"New regular user registered (pending approval): {email} (ID: {new_user.id})")
            
            # Don't automatically log in - user needs admin approval first
            return jsonify({
                "success": True,
                "message": "Registration successful! Your account is pending admin approval. You will be able to log in once an administrator approves your account.",
                "user_id": new_user.id,
                "email": new_user.email,
                "pending_approval": True
            })
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error registering user: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@bp.route("/login", methods=["POST"])
def login():
    """Login a user."""
    try:
        data = request.get_json() or {}
        email = data.get("email", "").strip().lower()
        password = data.get("password", "")
        
        if not email or not password:
            return jsonify({"error": "Email and password are required"}), 400
        
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(email=email).first()
            
            if not user or not check_password_hash(user.password_hash, password):
                return jsonify({"error": "Invalid email or password"}), 401
            
            # Check if user account is active (approved)
            if not user.is_active():
                return jsonify({"error": "Your account is pending admin approval. Please wait for an administrator to approve your account before logging in."}), 403
            
            # Log in the user
            login_user(user, remember=True)
            
            logger.info(f"User logged in: {email} (ID: {user.id})")
            
            return jsonify({
                "success": True,
                "message": "Login successful",
                "user_id": user.id,
                "email": user.email
            })
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error logging in user: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    """Logout the current user."""
    try:
        logout_user()
        return jsonify({"success": True, "message": "Logged out successfully"})
    except Exception as e:
        logger.error(f"Error logging out: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@bp.route("/me", methods=["GET"])
@login_required
def get_current_user():
    """Get current user information."""
    try:
        return jsonify({
            "user_id": current_user.id,
            "email": current_user.email,
            "role": current_user.role,
            "is_admin": current_user.is_admin(),
            "active": current_user.is_active()
        })
    except Exception as e:
        logger.error(f"Error getting current user: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

