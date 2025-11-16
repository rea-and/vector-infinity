"""Chat-related routes."""
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
import logging
from assistant_service import AssistantService
from vector_store_service import VectorStoreService
from database import ChatThread, SessionLocal

logger = logging.getLogger(__name__)

bp = Blueprint('chat', __name__, url_prefix='/api/chat')


@bp.route("/threads", methods=["GET"])
@login_required
def list_chat_threads():
    """List all chat threads for the current user."""
    db = SessionLocal()
    try:
        threads = db.query(ChatThread).filter(
            ChatThread.user_id == current_user.id
        ).order_by(ChatThread.updated_at.desc()).all()
        
        result = []
        for thread in threads:
            result.append({
                "id": thread.id,
                "thread_id": thread.thread_id,
                "title": thread.title or "New Chat",
                "created_at": thread.created_at.isoformat() if thread.created_at else None,
                "updated_at": thread.updated_at.isoformat() if thread.updated_at else None
            })
        
        return jsonify({"threads": result})
    except Exception as e:
        logger.error(f"Error listing threads: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@bp.route("/threads", methods=["POST"])
@login_required
def create_chat_thread():
    """Create a new chat thread."""
    db = SessionLocal()
    try:
        assistant_service = AssistantService()
        
        thread_id = assistant_service.create_thread()
        if not thread_id:
            return jsonify({"error": "Failed to create thread"}), 500
        
        # Save thread to database
        chat_thread = ChatThread(
            user_id=current_user.id,
            thread_id=thread_id,
            title=None  # Will be set from first message
        )
        db.add(chat_thread)
        db.commit()
        db.refresh(chat_thread)
        
        return jsonify({
            "thread_id": thread_id,
            "id": chat_thread.id,
            "title": chat_thread.title or "New Chat",
            "created_at": chat_thread.created_at.isoformat() if chat_thread.created_at else None
        })
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating thread: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@bp.route("/threads/<thread_id>/messages", methods=["POST"])
@login_required
def send_chat_message(thread_id):
    """Send a message in a chat thread."""
    db = SessionLocal()
    try:
        data = request.get_json() or {}
        message = data.get("message", "")
        
        if not message:
            return jsonify({"error": "message parameter is required"}), 400
        
        # Verify thread belongs to user
        chat_thread = db.query(ChatThread).filter(
            ChatThread.thread_id == thread_id,
            ChatThread.user_id == current_user.id
        ).first()
        
        if not chat_thread:
            return jsonify({"error": "Thread not found or access denied"}), 404
        
        assistant_service = AssistantService()
        vector_store_service = VectorStoreService()
        
        # Get unified vector store ID (user-specific)
        vector_store_id = vector_store_service.get_unified_vector_store_id(user_id=current_user.id)
        if not vector_store_id:
            return jsonify({"error": "No vector store found. Please run an import first."}), 404
        
        # Get or create unified assistant with vector store (user-specific)
        assistant_id = assistant_service.get_or_create_unified_assistant(vector_store_id, user_id=current_user.id)
        if not assistant_id:
            return jsonify({"error": "Failed to get or create assistant"}), 500
        
        # Send message and get response
        response = assistant_service.send_message(thread_id, assistant_id, message)
        if response is None:
            return jsonify({"error": "Failed to get response from assistant"}), 500
        
        # Update thread title from first message if not set
        if not chat_thread.title:
            # Use first 50 characters of message as title
            title = message[:50].strip()
            if len(message) > 50:
                title += "..."
            chat_thread.title = title
            db.commit()
        
        # Update thread's updated_at timestamp
        from datetime import datetime, timezone
        chat_thread.updated_at = datetime.now(timezone.utc)
        db.commit()
        
        return jsonify({
            "response": response,
            "thread_id": thread_id,
            "assistant_id": assistant_id
        })
    except Exception as e:
        db.rollback()
        logger.error(f"Error sending message: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@bp.route("/threads/<thread_id>/messages", methods=["GET"])
@login_required
def get_chat_messages(thread_id):
    """Get all messages from a chat thread."""
    try:
        assistant_service = AssistantService()
        
        messages = assistant_service.get_thread_messages(thread_id)
        return jsonify({"messages": messages})
    except Exception as e:
        logger.error(f"Error getting messages: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

