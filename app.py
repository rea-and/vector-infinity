"""Main Flask application."""
from flask import Flask, jsonify, request, render_template_string
from flask_cors import CORS
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from database import ImportLog, DataItem, SessionLocal, init_db
from importer import DataImporter
from scheduler import ImportScheduler
from plugin_loader import PluginLoader
import config
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Initialize services
init_db()
importer = DataImporter()
plugin_loader = PluginLoader()
scheduler = ImportScheduler()
scheduler.start()


@app.route("/")
def index():
    """Serve the main UI."""
    return render_template_string(open("templates/index.html").read())


@app.route("/api/plugins", methods=["GET"])
def list_plugins():
    """List all available plugins."""
    plugins = plugin_loader.get_all_plugins()
    result = []
    for name, plugin in plugins.items():
        result.append({
            "name": name,
            "enabled": plugin.config.get("enabled", False),
            "config_schema": plugin.get_config_schema()
        })
    return jsonify(result)


@app.route("/api/imports", methods=["GET"])
def list_imports():
    """List import logs."""
    db = SessionLocal()
    try:
        limit = request.args.get("limit", 50, type=int)
        plugin_name = request.args.get("plugin", None)
        
        query = db.query(ImportLog)
        if plugin_name:
            query = query.filter(ImportLog.plugin_name == plugin_name)
        
        logs = query.order_by(ImportLog.started_at.desc()).limit(limit).all()
        
        result = []
        for log in logs:
            result.append({
                "id": log.id,
                "plugin_name": log.plugin_name,
                "status": log.status,
                "started_at": log.started_at.isoformat() if log.started_at else None,
                "completed_at": log.completed_at.isoformat() if log.completed_at else None,
                "records_imported": log.records_imported,
                "error_message": log.error_message
            })
        
        return jsonify(result)
    finally:
        db.close()


@app.route("/api/imports/run", methods=["POST"])
def run_import():
    """Run import for a specific plugin or all plugins."""
    data = request.get_json() or {}
    plugin_name = data.get("plugin_name")
    
    if plugin_name:
        log_entry = importer.import_from_plugin(plugin_name)
        return jsonify({
            "success": log_entry.status == "success",
            "plugin_name": log_entry.plugin_name,
            "status": log_entry.status,
            "records_imported": log_entry.records_imported,
            "error_message": log_entry.error_message
        })
    else:
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


@app.route("/api/plugins/<plugin_name>/context", methods=["GET"])
def get_plugin_context(plugin_name):
    """Get context data from a specific plugin for Custom GPT."""
    db = SessionLocal()
    try:
        # Get query parameters
        limit = request.args.get("limit", 50, type=int)
        days = request.args.get("days", 30, type=int)
        item_type = request.args.get("item_type", None)
        query = request.args.get("query", None)  # Optional text search
        
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # Query data items
        db_query = db.query(DataItem).filter(
            DataItem.plugin_name == plugin_name,
            DataItem.created_at >= cutoff_date
        )
        
        if item_type:
            db_query = db_query.filter(DataItem.item_type == item_type)
        
        # Simple text search in title and content
        if query:
            db_query = db_query.filter(
                (DataItem.title.contains(query)) | 
                (DataItem.content.contains(query))
            )
        
        items = db_query.order_by(DataItem.created_at.desc()).limit(limit).all()
        
        # Format response
        result = {
            "plugin_name": plugin_name,
            "count": len(items),
            "items": []
        }
        
        for item in items:
            result["items"].append({
                "id": item.id,
                "type": item.item_type,
                "title": item.title,
                "content": item.content,
                "metadata": item.item_metadata,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "source_timestamp": item.source_timestamp.isoformat() if item.source_timestamp else None
            })
        
        return jsonify(result)
    finally:
        db.close()


@app.route("/api/plugins/<plugin_name>/search", methods=["GET"])
def search_plugin_context(plugin_name):
    """Search context data from a specific plugin."""
    query = request.args.get("q", "")
    if not query:
        return jsonify({"error": "Missing 'q' parameter"}), 400
    
    db = SessionLocal()
    try:
        limit = request.args.get("limit", 20, type=int)
        days = request.args.get("days", 30, type=int)
        
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        items = db.query(DataItem).filter(
            DataItem.plugin_name == plugin_name,
            DataItem.created_at >= cutoff_date,
            (DataItem.title.contains(query)) | 
            (DataItem.content.contains(query))
        ).order_by(DataItem.created_at.desc()).limit(limit).all()
        
        result = {
            "plugin_name": plugin_name,
            "query": query,
            "count": len(items),
            "items": []
        }
        
        for item in items:
            result["items"].append({
                "id": item.id,
                "type": item.item_type,
                "title": item.title,
                "content": item.content[:500],  # Truncate for search results
                "created_at": item.created_at.isoformat() if item.created_at else None
            })
        
        return jsonify(result)
    finally:
        db.close()


@app.route("/api/stats", methods=["GET"])
def get_stats():
    """Get statistics about imported data."""
    db = SessionLocal()
    try:
        total_items = db.query(DataItem).count()
        items_by_plugin = {}
        items_by_type = {}
        
        for item in db.query(DataItem).all():
            items_by_plugin[item.plugin_name] = items_by_plugin.get(item.plugin_name, 0) + 1
            items_by_type[item.item_type] = items_by_type.get(item.item_type, 0) + 1
        
        return jsonify({
            "total_items": total_items,
            "by_plugin": items_by_plugin,
            "by_type": items_by_type
        })
    finally:
        db.close()


if __name__ == "__main__":
    app.run(host=config.WEB_HOST, port=config.WEB_PORT, debug=False)

