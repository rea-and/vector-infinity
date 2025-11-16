"""Chat-related routes."""
from flask import Blueprint, jsonify, request
import logging
from assistant_service import AssistantService
from vector_store_service import VectorStoreService

logger = logging.getLogger(__name__)

bp = Blueprint('chat', __name__, url_prefix='/api/chat')


@bp.route("/threads", methods=["POST"])
def create_chat_thread():
    """Create a new chat thread."""
    try:
        assistant_service = AssistantService()
        
        thread_id = assistant_service.create_thread()
        if not thread_id:
            return jsonify({"error": "Failed to create thread"}), 500
        
        return jsonify({"thread_id": thread_id})
    except Exception as e:
        logger.error(f"Error creating thread: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@bp.route("/threads/<thread_id>/messages", methods=["POST"])
def send_chat_message(thread_id):
    """Send a message in a chat thread."""
    try:
        data = request.get_json() or {}
        message = data.get("message", "")
        
        if not message:
            return jsonify({"error": "message parameter is required"}), 400
        
        assistant_service = AssistantService()
        vector_store_service = VectorStoreService()
        
        # Get unified vector store ID
        vector_store_id = vector_store_service.get_unified_vector_store_id()
        if not vector_store_id:
            return jsonify({"error": "No vector store found. Please run an import first."}), 404
        
        # Get or create unified assistant with vector store
        assistant_id = assistant_service.get_or_create_unified_assistant(vector_store_id)
        if not assistant_id:
            return jsonify({"error": "Failed to get or create assistant"}), 500
        
        # Send message and get response
        response = assistant_service.send_message(thread_id, assistant_id, message)
        if response is None:
            return jsonify({"error": "Failed to get response from assistant"}), 500
        
        return jsonify({
            "response": response,
            "thread_id": thread_id,
            "assistant_id": assistant_id
        })
    except Exception as e:
        logger.error(f"Error sending message: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@bp.route("/threads/<thread_id>/messages", methods=["GET"])
def get_chat_messages(thread_id):
    """Get all messages from a chat thread."""
    try:
        assistant_service = AssistantService()
        
        messages = assistant_service.get_thread_messages(thread_id)
        return jsonify({"messages": messages})
    except Exception as e:
        logger.error(f"Error getting messages: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

