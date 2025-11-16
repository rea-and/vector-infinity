"""User management routes (admin only)."""
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
import logging
from database import User, SessionLocal
from werkzeug.security import generate_password_hash

logger = logging.getLogger(__name__)

bp = Blueprint('users', __name__, url_prefix='/api/users')


def require_admin():
    """Check if current user is admin, return error if not."""
    if not current_user.is_authenticated or not current_user.is_admin():
        return jsonify({"error": "Admin access required"}), 403
    return None


@bp.route("", methods=["GET"])
@login_required
def list_users():
    """List all users (admin only)."""
    error = require_admin()
    if error:
        return error
    
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.created_at.desc()).all()
        
        result = []
        for user in users:
            result.append({
                "id": user.id,
                "email": user.email,
                "role": user.role,
                "active": user.is_active(),
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "updated_at": user.updated_at.isoformat() if user.updated_at else None
            })
        
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error listing users: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@bp.route("/pending", methods=["GET"])
@login_required
def list_pending_users():
    """List pending users awaiting approval (admin only)."""
    error = require_admin()
    if error:
        return error
    
    db = SessionLocal()
    try:
        pending_users = db.query(User).filter(User.active == 0).order_by(User.created_at.asc()).all()
        
        result = []
        for user in pending_users:
            result.append({
                "id": user.id,
                "email": user.email,
                "role": user.role,
                "created_at": user.created_at.isoformat() if user.created_at else None
            })
        
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error listing pending users: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@bp.route("/<int:user_id>/approve", methods=["POST"])
@login_required
def approve_user(user_id):
    """Approve a user account (admin only)."""
    error = require_admin()
    if error:
        return error
    
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(id=user_id).first()
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        user.active = 1
        db.commit()
        
        logger.info(f"User {user.email} (ID: {user_id}) approved by admin {current_user.email}")
        
        return jsonify({
            "success": True,
            "message": f"User {user.email} has been approved"
        })
    except Exception as e:
        db.rollback()
        logger.error(f"Error approving user: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@bp.route("/<int:user_id>/decline", methods=["POST"])
@login_required
def decline_user(user_id):
    """Decline/delete a user account (admin only)."""
    error = require_admin()
    if error:
        return error
    
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(id=user_id).first()
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        user_email = user.email
        db.delete(user)
        db.commit()
        
        logger.info(f"User {user_email} (ID: {user_id}) declined/deleted by admin {current_user.email}")
        
        return jsonify({
            "success": True,
            "message": f"User {user_email} has been declined and removed"
        })
    except Exception as e:
        db.rollback()
        logger.error(f"Error declining user: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@bp.route("/<int:user_id>/deactivate", methods=["POST"])
@login_required
def deactivate_user(user_id):
    """Deactivate a user account (admin only)."""
    error = require_admin()
    if error:
        return error
    
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(id=user_id).first()
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        # Prevent deactivating yourself
        if user.id == current_user.id:
            return jsonify({"error": "You cannot deactivate your own account"}), 400
        
        user.active = 0
        db.commit()
        
        logger.info(f"User {user.email} (ID: {user_id}) deactivated by admin {current_user.email}")
        
        return jsonify({
            "success": True,
            "message": f"User {user.email} has been deactivated"
        })
    except Exception as e:
        db.rollback()
        logger.error(f"Error deactivating user: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()

