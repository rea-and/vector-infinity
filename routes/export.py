"""Export-related routes."""
from flask import Blueprint, send_file, Response
import logging
from io import StringIO
from database import DataItem, SessionLocal
from datetime import datetime

logger = logging.getLogger(__name__)

bp = Blueprint('export', __name__, url_prefix='/api/export')


@bp.route("/emails", methods=["GET"])
def export_emails():
    """Export all imported emails to a text file for ChatGPT knowledge upload."""
    db = SessionLocal()
    try:
        # Get all email items
        emails = db.query(DataItem).filter(DataItem.item_type == "email").order_by(DataItem.source_timestamp).all()
        
        if not emails:
            return jsonify({"error": "No emails found to export"}), 404
        
        # Create text content
        output = StringIO()
        output.write("EMAIL EXPORT\n")
        output.write("=" * 80 + "\n\n")
        output.write(f"Total emails: {len(emails)}\n")
        output.write(f"Export date: {datetime.now().isoformat()}\n\n")
        output.write("=" * 80 + "\n\n")
        
        for email in emails:
            output.write(f"Subject: {email.title or '(No subject)'}\n")
            output.write(f"From: {email.item_metadata.get('from', 'Unknown') if email.item_metadata else 'Unknown'}\n")
            output.write(f"Date: {email.source_timestamp.isoformat() if email.source_timestamp else 'Unknown'}\n")
            output.write("-" * 80 + "\n")
            output.write(f"{email.content or '(No content)'}\n")
            output.write("\n" + "=" * 80 + "\n\n")
        
        # Create response with file download
        output.seek(0)
        response = Response(
            output.getvalue(),
            mimetype='text/plain',
            headers={
                'Content-Disposition': f'attachment; filename=emails_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
            }
        )
        return response
        
    except Exception as e:
        logger.error(f"Error exporting emails: {e}", exc_info=True)
        return jsonify({"error": f"Error exporting emails: {str(e)}"}), 500
    finally:
        db.close()


@bp.route("/whoop", methods=["GET"])
def export_whoop():
    """Export all imported WHOOP data to a text file."""
    db = SessionLocal()
    try:
        # Get all WHOOP items (recovery, sleep, workout)
        whoop_items = db.query(DataItem).filter(
            DataItem.item_type.in_(["whoop_recovery", "whoop_sleep", "whoop_workout"])
        ).order_by(DataItem.source_timestamp).all()
        
        if not whoop_items:
            return jsonify({"error": "No WHOOP data found to export"}), 404
        
        # Create text content
        output = StringIO()
        output.write("WHOOP DATA EXPORT\n")
        output.write("=" * 80 + "\n\n")
        output.write(f"Total records: {len(whoop_items)}\n")
        output.write(f"Export date: {datetime.now().isoformat()}\n\n")
        output.write("=" * 80 + "\n\n")
        
        for item in whoop_items:
            output.write(f"Type: {item.item_type.replace('whoop_', '').upper()}\n")
            output.write(f"Date: {item.source_timestamp.isoformat() if item.source_timestamp else 'Unknown'}\n")
            if item.title:
                output.write(f"Title: {item.title}\n")
            output.write("-" * 80 + "\n")
            output.write(f"{item.content or '(No content)'}\n")
            output.write("\n" + "=" * 80 + "\n\n")
        
        # Create response with file download
        output.seek(0)
        response = Response(
            output.getvalue(),
            mimetype='text/plain',
            headers={
                'Content-Disposition': f'attachment; filename=whoop_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
            }
        )
        return response
        
    except Exception as e:
        logger.error(f"Error exporting WHOOP data: {e}", exc_info=True)
        return jsonify({"error": f"Error exporting WHOOP data: {str(e)}"}), 500
    finally:
        db.close()

