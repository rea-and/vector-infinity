"""Data management routes."""
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
import os
import tempfile
import logging
from pathlib import Path
from datetime import datetime, timezone
from database import ImportLog, DataItem, SessionLocal, engine, Base
from vector_store_service import VectorStoreService
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
def factory_reset():
    """Factory reset: Delete absolutely everything - database, logs, temp files, vector store."""
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
            "vector_store_files_deleted": 0,
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
        
        # 5. Delete OpenAI vector store files (optional - may fail if API key not set)
        try:
            vector_store_service = VectorStoreService()
            vector_store_id = vector_store_service.get_unified_vector_store_id()
            
            if vector_store_id:
                # List all files in the vector store (handle pagination)
                all_files = []
                has_more = True
                after = None
                
                while has_more:
                    params = {"vector_store_id": vector_store_id, "limit": 100}
                    if after:
                        params["after"] = after
                    
                    files = vector_store_service.client.vector_stores.files.list(**params)
                    
                    if hasattr(files, 'data') and files.data:
                        all_files.extend(files.data)
                        # Check if there are more pages
                        has_more = hasattr(files, 'has_more') and files.has_more
                        if has_more and files.data:
                            after = files.data[-1].id
                        else:
                            has_more = False
                    else:
                        has_more = False
                
                # Delete all files
                for file_item in all_files:
                    try:
                        # Delete file from vector store
                        vector_store_service.client.vector_stores.files.delete(
                            vector_store_id=vector_store_id,
                            file_id=file_item.id
                        )
                        results["vector_store_files_deleted"] += 1
                    except Exception as e:
                        error_msg = f"Error deleting vector store file {file_item.id}: {e}"
                        logger.warning(error_msg)
                        results["errors"].append(error_msg)
                
                logger.info(f"Deleted {results['vector_store_files_deleted']} files from vector store")
        except Exception as e:
            # This is optional - don't fail if vector store deletion fails
            error_msg = f"Error clearing vector store (optional): {e}"
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


@bp.route("/vector-store/info", methods=["GET"])
@login_required
def get_vector_store_info():
    """Get information about the unified vector store."""
    try:
        vector_store_service = VectorStoreService()
        
        info = vector_store_service.get_vector_store_info(user_id=current_user.id)
        if not info:
            return jsonify({"error": "Vector store not found or not accessible"}), 404
        
        return jsonify(info)
    except Exception as e:
        logger.error(f"Error getting vector store info: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@bp.route("/vector-store/reupload", methods=["POST"])
@login_required
def reupload_all_data_to_vector_store():
    """Re-upload all existing data from the database to the vector store."""
    try:
        vector_store_service = VectorStoreService()
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
                logger.info(f"Re-uploading {len(items)} items from {plugin_name} to vector store")
                
                # Upload in batches (optimized - don't wait for processing on each batch)
                batch_size = 500  # Increased batch size for better performance
                plugin_uploaded = 0
                total_batches = (len(items) + batch_size - 1) // batch_size
                
                for batch_start in range(0, len(items), batch_size):
                    batch_end = min(batch_start + batch_size, len(items))
                    batch_items = items[batch_start:batch_end]
                    batch_num = batch_start // batch_size + 1
                    
                    # Only wait for processing on the last batch
                    wait_for_processing = (batch_num == total_batches)
                    success = vector_store_service.upload_data_to_vector_store(plugin_name, batch_items, user_id=current_user.id, wait_for_processing=wait_for_processing)
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
        logger.error(f"Error re-uploading data to vector store: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

