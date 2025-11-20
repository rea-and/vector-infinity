"""Data management routes."""
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
import os
import tempfile
import logging
from pathlib import Path
from datetime import datetime, timezone
from database import ImportLog, DataItem, SessionLocal, engine, Base, UserSettings
from file_search_service import FileSearchService
import config

logger = logging.getLogger(__name__)

bp = Blueprint('data', __name__, url_prefix='/api')


@bp.route("/data/clear", methods=["POST"])
@login_required
def clear_all_data():
    """Clear all imported data from the database."""
    db = SessionLocal()
    try:
        # Get confirmation from request
        data = request.get_json() or {}
        confirm = data.get("confirm", False)
        
        if not confirm:
            return jsonify({"error": "Confirmation required. Set 'confirm': true in request body."}), 400
        
        # Count items before deletion (user-specific)
        total_items = db.query(DataItem).filter(DataItem.user_id == current_user.id).count()
        
        # Delete all data items for this user
        db.query(DataItem).filter(DataItem.user_id == current_user.id).delete()
        
        # Optionally clear import logs (commented out - uncomment if you want to clear logs too)
        # db.query(ImportLog).delete()
        
        db.commit()
        
        logger.info(f"Cleared {total_items} data items from database")
        
        return jsonify({
            "success": True,
            "message": f"Successfully cleared {total_items} data items from database",
            "items_deleted": total_items
        })
    except Exception as e:
        db.rollback()
        logger.error(f"Error clearing data: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@bp.route("/factory-reset", methods=["POST"])
@login_required
def factory_reset():
    """Factory reset: Delete absolutely everything - database, logs, temp files, file search store."""
    try:
        # Get confirmation from request
        data = request.get_json() or {}
        confirm = data.get("confirm", False)
        
        if not confirm:
            return jsonify({"error": "Confirmation required. Set 'confirm': true in request body."}), 400
        
        results = {
            "database_items_deleted": 0,
            "database_logs_deleted": 0,
            "temp_files_deleted": 0,
            "log_files_deleted": 0,
            "file_search_store_note": "",
            "errors": []
        }
        
        # 1. Clear all database data for this user
        db = SessionLocal()
        try:
            results["database_items_deleted"] = db.query(DataItem).filter(DataItem.user_id == current_user.id).count()
            results["database_logs_deleted"] = db.query(ImportLog).filter(ImportLog.user_id == current_user.id).count()
            
            db.query(DataItem).filter(DataItem.user_id == current_user.id).delete()
            db.query(ImportLog).filter(ImportLog.user_id == current_user.id).delete()
            db.commit()
            logger.info(f"Cleared {results['database_items_deleted']} data items and {results['database_logs_deleted']} import logs")
        except Exception as e:
            db.rollback()
            error_msg = f"Error clearing database: {e}"
            logger.error(error_msg, exc_info=True)
            results["errors"].append(error_msg)
        finally:
            db.close()
        
        # 2. Delete temporary upload files
        try:
            temp_upload_dir = Path(tempfile.gettempdir()) / "vector_infinity_uploads"
            if temp_upload_dir.exists():
                temp_files = list(temp_upload_dir.glob("*"))
                for temp_file in temp_files:
                    try:
                        if temp_file.is_file():
                            temp_file.unlink()
                            results["temp_files_deleted"] += 1
                    except Exception as e:
                        error_msg = f"Error deleting temp file {temp_file}: {e}"
                        logger.warning(error_msg)
                        results["errors"].append(error_msg)
                logger.info(f"Deleted {results['temp_files_deleted']} temporary files")
        except Exception as e:
            error_msg = f"Error deleting temp files: {e}"
            logger.error(error_msg, exc_info=True)
            results["errors"].append(error_msg)
        
        # 3. Delete log files
        try:
            if config.LOGS_DIR.exists():
                log_files = list(config.LOGS_DIR.glob("*"))
                for log_file in log_files:
                    try:
                        if log_file.is_file():
                            log_file.unlink()
                            results["log_files_deleted"] += 1
                    except Exception as e:
                        error_msg = f"Error deleting log file {log_file}: {e}"
                        logger.warning(error_msg)
                        results["errors"].append(error_msg)
                logger.info(f"Deleted {results['log_files_deleted']} log files")
        except Exception as e:
            error_msg = f"Error deleting log files: {e}"
            logger.error(error_msg, exc_info=True)
            results["errors"].append(error_msg)
        
        # 4. Clear OAuth flows in memory
        try:
            from services import oauth_flows as oauth_flows_dict
            oauth_flows_dict.clear()
            logger.info("Cleared OAuth flows from memory")
        except Exception as e:
            error_msg = f"Error clearing OAuth flows: {e}"
            logger.warning(error_msg)
            results["errors"].append(error_msg)
        
        # 5. Note about File Search Store (files are managed automatically by Gemini)
        try:
            file_search_service = FileSearchService()
            store_name = file_search_service.get_unified_file_search_store_name(user_id=current_user.id)
            
            if store_name:
                logger.info(f"File Search Store {store_name} exists. Files are managed automatically by Gemini.")
                results["file_search_store_note"] = "File Search Store files are managed by Gemini and will be updated on next import"
        except Exception as e:
            # This is optional - don't fail if File Search Store access fails
            error_msg = f"Error accessing File Search Store (optional): {e}"
            logger.warning(error_msg)
            results["errors"].append(error_msg)
        
        # 6. Recreate database (drop and recreate)
        try:
            # Close any existing connections
            Base.metadata.drop_all(bind=engine)
            Base.metadata.create_all(bind=engine)
            logger.info("Recreated database schema")
        except Exception as e:
            error_msg = f"Error recreating database: {e}"
            logger.error(error_msg, exc_info=True)
            results["errors"].append(error_msg)
        
        success = len(results["errors"]) == 0 or (
            results["database_items_deleted"] > 0 or 
            results["database_logs_deleted"] > 0 or
            results["temp_files_deleted"] > 0
        )
        
        return jsonify({
            "success": success,
            "message": "Factory reset completed",
            "results": results
        })
    except Exception as e:
        logger.error(f"Error during factory reset: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@bp.route("/stats", methods=["GET"])
@login_required
def get_stats():
    """Get statistics about imported data for the current user."""
    db = SessionLocal()
    try:
        total_items = db.query(DataItem).filter(DataItem.user_id == current_user.id).count()
        items_by_plugin = {}
        items_by_type = {}
        
        for item in db.query(DataItem).filter(DataItem.user_id == current_user.id).all():
            items_by_plugin[item.plugin_name] = items_by_plugin.get(item.plugin_name, 0) + 1
            items_by_type[item.item_type] = items_by_type.get(item.item_type, 0) + 1
        
        # Get database file size
        db_size_bytes = 0
        db_size_human = "0 B"
        if os.path.exists(config.DATABASE_PATH):
            db_size_bytes = os.path.getsize(config.DATABASE_PATH)
            # Convert to human-readable format
            size = float(db_size_bytes)
            for unit in ['B', 'KB', 'MB', 'GB']:
                if size < 1024.0:
                    db_size_human = f"{size:.2f} {unit}"
                    break
                size /= 1024.0
            else:
                db_size_human = f"{size:.2f} TB"
        
        return jsonify({
            "total_items": total_items,
            "by_plugin": items_by_plugin,
            "by_type": items_by_type,
            "database_size_bytes": db_size_bytes,
            "database_size": db_size_human
        })
    finally:
        db.close()


@bp.route("/file-search-store/info", methods=["GET"])
@login_required
def get_file_search_store_info():
    """Get information about the unified File Search Store."""
    try:
        file_search_service = FileSearchService()
        
        info = file_search_service.get_file_search_store_info(user_id=current_user.id)
        if not info:
            return jsonify({"error": "File Search Store not found or not accessible"}), 404
        
        return jsonify(info)
    except Exception as e:
        logger.error(f"Error getting File Search Store info: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@bp.route("/file-search-store/reupload", methods=["POST"])
@login_required
def reupload_all_data_to_file_search_store():
    """Re-upload all existing data from the database to the File Search Store."""
    try:
        file_search_service = FileSearchService()
        db = SessionLocal()
        
        try:
            # Get all data items from database for this user
            all_items = db.query(DataItem).filter(DataItem.user_id == current_user.id).all()
            
            if not all_items:
                return jsonify({"error": "No data items found in database"}), 404
            
            # Group by plugin
            items_by_plugin = {}
            for item in all_items:
                if item.plugin_name not in items_by_plugin:
                    items_by_plugin[item.plugin_name] = []
                
                items_by_plugin[item.plugin_name].append({
                    "source_id": item.source_id,
                    "item_type": item.item_type,
                    "title": item.title,
                    "content": item.content,
                    "metadata": item.item_metadata or {},
                    "source_timestamp": item.source_timestamp
                })
            
            # Upload each plugin's data
            total_uploaded = 0
            results = {}
            
            for plugin_name, items in items_by_plugin.items():
                logger.info(f"Re-uploading {len(items)} items from {plugin_name} to File Search Store")
                
                # Upload in batches (optimized - don't wait for processing on each batch)
                batch_size = 500  # Batch size for File Search Store uploads
                plugin_uploaded = 0
                total_batches = (len(items) + batch_size - 1) // batch_size
                
                for batch_start in range(0, len(items), batch_size):
                    batch_end = min(batch_start + batch_size, len(items))
                    batch_items = items[batch_start:batch_end]
                    batch_num = batch_start // batch_size + 1
                    
                    # Only wait for processing on the last batch
                    wait_for_processing = (batch_num == total_batches)
                    success = file_search_service.upload_data_to_file_search_store(
                        plugin_name, batch_items, user_id=current_user.id, wait_for_processing=wait_for_processing
                    )
                    if success:
                        plugin_uploaded += len(batch_items)
                        total_uploaded += len(batch_items)
                
                results[plugin_name] = {
                    "total_items": len(items),
                    "uploaded": plugin_uploaded
                }
            
            return jsonify({
                "success": True,
                "total_items": len(all_items),
                "total_uploaded": total_uploaded,
                "results": results
            })
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error re-uploading data to File Search Store: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@bp.route("/settings/assistant-instructions", methods=["GET"])
@login_required
def get_assistant_instructions():
    """Get the current assistant instructions for the user."""
    db = SessionLocal()
    try:
        settings = db.query(UserSettings).filter(UserSettings.user_id == current_user.id).first()
        
        default_instructions = "You are a helpful assistant that can answer questions using both your general knowledge and any relevant context from imported data (Gmail, WhatsApp, WHOOP, etc.). Answer questions naturally and directly. If you find relevant information in the imported data, mention the source when helpful. If the question is about general topics not covered in the imported data, answer using your general knowledge without mentioning that the information wasn't found in the files. Be concise and helpful."
        
        instructions = default_instructions
        if settings and settings.assistant_instructions:
            instructions = settings.assistant_instructions
        
        return jsonify({
            "instructions": instructions,
            "is_custom": settings is not None and settings.assistant_instructions is not None
        })
    finally:
        db.close()


@bp.route("/settings/assistant-instructions", methods=["POST"])
@login_required
def update_assistant_instructions():
    """Update the assistant instructions for the user."""
    db = SessionLocal()
    try:
        data = request.get_json() or {}
        instructions = data.get("instructions", "").strip()
        
        if not instructions:
            return jsonify({"error": "Instructions cannot be empty"}), 400
        
        # Get or create user settings
        settings = db.query(UserSettings).filter(UserSettings.user_id == current_user.id).first()
        
        if not settings:
            settings = UserSettings(user_id=current_user.id, assistant_instructions=instructions)
            db.add(settings)
        else:
            settings.assistant_instructions = instructions
            settings.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        db.refresh(settings)
        
        logger.info(f"Updated assistant instructions for user {current_user.id}")
        
        return jsonify({
            "success": True,
            "message": "Assistant instructions updated successfully",
            "instructions": settings.assistant_instructions
        })
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating assistant instructions: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@bp.route("/settings/assistant-model", methods=["GET"])
@login_required
def get_assistant_model():
    """Get the current assistant model for the user and available models."""
    db = SessionLocal()
    try:
        settings = db.query(UserSettings).filter(UserSettings.user_id == current_user.id).first()
        
        model = config.DEFAULT_MODEL
        if settings and settings.assistant_model:
            # Validate that the user's model is still available
            if settings.assistant_model in config.AVAILABLE_MODELS:
                model = settings.assistant_model
            else:
                # User's model is no longer available, use default
                logger.warning(f"User {current_user.id} has model {settings.assistant_model} which is no longer available")
        
        # Return available models with their display names
        available_models = []
        for model_name in config.AVAILABLE_MODELS:
            available_models.append({
                "value": model_name,
                "label": config.MODEL_DISPLAY_NAMES.get(model_name, model_name)
            })
        
        return jsonify({
            "model": model,
            "is_custom": settings is not None and settings.assistant_model is not None and settings.assistant_model in config.AVAILABLE_MODELS,
            "available_models": available_models,
            "default_model": config.DEFAULT_MODEL
        })
    finally:
        db.close()


@bp.route("/settings/assistant-model", methods=["POST"])
@login_required
def update_assistant_model():
    """Update the assistant model for the user."""
    db = SessionLocal()
    try:
        data = request.get_json() or {}
        model = data.get("model", "").strip()
        
        # Validate model
        if not model:
            return jsonify({"error": "Model cannot be empty"}), 400
        
        if model not in config.AVAILABLE_MODELS:
            return jsonify({"error": f"Invalid model. Must be one of: {', '.join(config.AVAILABLE_MODELS)}"}), 400
        
        # Get or create user settings
        settings = db.query(UserSettings).filter(UserSettings.user_id == current_user.id).first()
        
        if not settings:
            settings = UserSettings(user_id=current_user.id, assistant_model=model)
            db.add(settings)
        else:
            settings.assistant_model = model
            settings.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        db.refresh(settings)
        
        logger.info(f"Updated assistant model for user {current_user.id} to {model}")
        
        return jsonify({
            "success": True,
            "message": "Assistant model updated successfully",
            "model": settings.assistant_model
        })
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating assistant model: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()

