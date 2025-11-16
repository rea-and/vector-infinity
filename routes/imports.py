"""Import-related routes."""
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from datetime import datetime, timezone
import tempfile
import secrets
import logging
from pathlib import Path
from database import ImportLog, SessionLocal
from services import importer
import config

logger = logging.getLogger(__name__)

bp = Blueprint('imports', __name__, url_prefix='/api/imports')


@bp.route("", methods=["GET"])
@login_required
def list_imports():
    """List import logs for the current user."""
    db = SessionLocal()
    try:
        limit = request.args.get("limit", 50, type=int)
        plugin_name = request.args.get("plugin", None)
        
        query = db.query(ImportLog).filter(ImportLog.user_id == current_user.id)
        if plugin_name:
            query = query.filter(ImportLog.plugin_name == plugin_name)
        
        logs = query.order_by(ImportLog.started_at.desc()).limit(limit).all()
        
        result = []
        for log in logs:
            progress_percent = 0
            if log.progress_total and log.progress_total > 0:
                progress_percent = int((log.progress_current / log.progress_total) * 100)
            
            result.append({
                "id": log.id,
                "plugin_name": log.plugin_name,
                "status": log.status,
                "started_at": log.started_at.isoformat() if log.started_at else None,
                "completed_at": log.completed_at.isoformat() if log.completed_at else None,
                "records_imported": log.records_imported,
                "error_message": log.error_message,
                "progress_current": log.progress_current or 0,
                "progress_total": log.progress_total or 0,
                "progress_percent": progress_percent,
                "progress_message": log.progress_message or ""
            })
        
        return jsonify(result)
    finally:
        db.close()


@bp.route("/run", methods=["POST"])
@login_required
def run_import():
    """Run import for a specific plugin or all plugins (async)."""
    plugin_name = None
    uploaded_file_path = None
    
    # Check if this is a file upload (multipart/form-data)
    if request.content_type and 'multipart/form-data' in request.content_type:
        plugin_name = request.form.get("plugin_name")
        if 'file' in request.files:
            file = request.files['file']
            if file.filename:
                # Save uploaded file to user-specific temporary location
                user_temp_dir = config.USER_DATA_DIR / str(current_user.id) / "uploads"
                user_temp_dir.mkdir(parents=True, exist_ok=True)
                uploaded_file_path = user_temp_dir / f"{plugin_name}_{secrets.token_hex(8)}_{file.filename}"
                file.save(str(uploaded_file_path))
                logger.info(f"Saved uploaded file to: {uploaded_file_path}")
    else:
        # JSON request
        data = request.get_json() or {}
        plugin_name = data.get("plugin_name")
    
    if plugin_name:
        # Create log entry first
        db = SessionLocal()
        try:
            log_entry = ImportLog(
                user_id=current_user.id,
                plugin_name=plugin_name,
                status="running",
                started_at=datetime.now(timezone.utc),
                progress_message="Starting import..."
            )
            db.add(log_entry)
            db.commit()
            log_id = log_entry.id
        finally:
            db.close()
        
        # Start import in background thread
        # Pass uploaded_file_path and user_id to the async function
        importer.import_from_plugin_async(plugin_name, log_id, user_id=current_user.id, uploaded_file_path=str(uploaded_file_path) if uploaded_file_path else None)
        
        return jsonify({
            "success": True,
            "log_id": log_id,
            "plugin_name": plugin_name,
            "status": "running",
            "message": "Import started in background"
        })
    else:
        # For "import all", run synchronously (could be improved later)
        results = importer.import_all()
        return jsonify({
            "success": True,
            "results": {
                name: {
                    "status": log.status,
                    "records_imported": log.records_imported,
                    "error_message": log.error_message
                }
                for name, log in results.items()
            }
        })


@bp.route("/<int:log_id>/status", methods=["GET"])
@login_required
def get_import_status(log_id):
    """Get the current status of an import."""
    db = SessionLocal()
    try:
        log_entry = db.query(ImportLog).filter_by(id=log_id, user_id=current_user.id).first()
        if not log_entry:
            return jsonify({"error": "Import log not found"}), 404
        
        progress_percent = 0
        if log_entry.progress_total > 0:
            progress_percent = int((log_entry.progress_current / log_entry.progress_total) * 100)
        
        return jsonify({
            "id": log_entry.id,
            "plugin_name": log_entry.plugin_name,
            "status": log_entry.status,
            "records_imported": log_entry.records_imported or 0,
            "progress_current": log_entry.progress_current or 0,
            "progress_total": log_entry.progress_total or 0,
            "progress_percent": progress_percent,
            "progress_message": log_entry.progress_message or "",
            "error_message": log_entry.error_message,
            "started_at": log_entry.started_at.isoformat() if log_entry.started_at else None,
            "completed_at": log_entry.completed_at.isoformat() if log_entry.completed_at else None
        })
    finally:
        db.close()

