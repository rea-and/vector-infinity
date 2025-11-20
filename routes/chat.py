"""Chat-related routes."""
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
import logging
from chat_service import ChatService
from database import ChatThread, SessionLocal
from datetime import datetime, timezone

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
        
        logger.info(f"Found {len(threads)} threads for user {current_user.id}")
        
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
    """Create a new chat thread (conversation)."""
    db = SessionLocal()
    try:
        # Generate a unique thread ID for our internal tracking
        import uuid
        thread_id = f"conv_{uuid.uuid4().hex[:16]}"
        
        # Thread ID will be set when first message is sent
        # Save thread to database
        chat_thread = ChatThread(
            user_id=current_user.id,
            thread_id=thread_id,  # Internal thread ID
            openai_thread_id=None,  # Will be set when first message is sent (reusing field name for compatibility)
            previous_response_id=None,
            conversation_history=None,
            title=None  # Will be set from first message
        )
        db.add(chat_thread)
        db.commit()
        db.refresh(chat_thread)
        
        logger.info(f"Created chat thread {thread_id} for user {current_user.id}, DB ID: {chat_thread.id}")
        
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
    """Send a message in a chat thread using Assistants API with vector store support."""
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
        
        chat_service = ChatService()
        
        # Get thread ID (stored in openai_thread_id field for database compatibility)
        thread_id = chat_thread.openai_thread_id
        
        # Send message and get response
        result = chat_service.send_message(
            message=message,
            thread_id=thread_id,
            user_id=current_user.id
        )
        
        if result is None:
            return jsonify({"error": "Failed to get response from chat service"}), 500
        
        # Update thread with thread ID and conversation history
        chat_thread.openai_thread_id = result["openai_thread_id"]  # Reusing field name for compatibility
        chat_thread.conversation_history = result["messages"]
        chat_thread.previous_response_id = result["response_id"]
        chat_thread.updated_at = datetime.now(timezone.utc)
        
        # Update thread title from first message if not set
        if not chat_thread.title or chat_thread.title.strip() == "":
            # Use first 50 characters of message as title
            title = message[:50].strip()
            if len(message) > 50:
                title += "..."
            chat_thread.title = title
            logger.info(f"Set thread title to: {title} for thread {thread_id}")
        
        db.commit()
        
        return jsonify({
            "response": result["content"],
            "thread_id": thread_id,
            "response_id": result["response_id"]
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
    db = SessionLocal()
    try:
        # Verify thread belongs to user
        chat_thread = db.query(ChatThread).filter(
            ChatThread.thread_id == thread_id,
            ChatThread.user_id == current_user.id
        ).first()
        
        if not chat_thread:
            return jsonify({"error": "Thread not found or access denied"}), 404
        
        # Use local conversation history (Gemini stores history in database)
        conversation_history = chat_thread.conversation_history if chat_thread.conversation_history else []
        
        # Convert to the format expected by the frontend
        messages = []
        for msg in conversation_history:
            messages.append({
                "role": msg.get("role"),
                "content": msg.get("content"),
                "created_at": chat_thread.updated_at.isoformat() if chat_thread.updated_at else None
            })
        
        return jsonify({"messages": messages})
    except Exception as e:
        logger.error(f"Error getting messages: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@bp.route("/threads/<thread_id>", methods=["DELETE"])
@login_required
def delete_chat_thread(thread_id):
    """Delete a chat thread."""
    db = SessionLocal()
    try:
        # Verify thread belongs to user
        chat_thread = db.query(ChatThread).filter(
            ChatThread.thread_id == thread_id,
            ChatThread.user_id == current_user.id
        ).first()
        
        if not chat_thread:
            return jsonify({"error": "Thread not found or access denied"}), 404
        
        # Delete the thread
        db.delete(chat_thread)
        db.commit()
        
        logger.info(f"Deleted chat thread {thread_id} for user {current_user.id}")
        
        return jsonify({"success": True, "message": "Thread deleted successfully"})
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting thread: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()

