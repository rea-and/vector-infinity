"""Export-related routes."""
from flask import Blueprint, send_file, Response, jsonify
from flask_login import login_required, current_user
import logging
from io import StringIO
from database import DataItem, SessionLocal
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

bp = Blueprint('export', __name__, url_prefix='/api/export')


@bp.route("/emails", methods=["GET"])
@login_required
def export_emails():
    """Export all imported emails to a text file for ChatGPT knowledge upload."""
    db = SessionLocal()
    try:
        # Query all emails from gmail_personal plugin for this user
        emails = db.query(DataItem).filter(
            DataItem.user_id == current_user.id,
            DataItem.plugin_name == "gmail_personal",
            DataItem.item_type == "email"
        ).order_by(DataItem.source_timestamp.desc()).all()
        
        if not emails:
            return jsonify({"error": "No emails found to export"}), 404
        
        # Format emails for ChatGPT knowledge upload
        lines = []
        lines.append("=" * 80)
        lines.append("EMAIL EXPORT FOR CHATGPT KNOWLEDGE")
        lines.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        lines.append(f"Total Emails: {len(emails)}")
        lines.append("=" * 80)
        lines.append("")
        
        for idx, email in enumerate(emails, 1):
            lines.append(f"EMAIL #{idx}")
            lines.append("-" * 80)
            
            # Subject
            if email.title:
                lines.append(f"Subject: {email.title}")
            
            # Metadata
            if email.item_metadata:
                metadata = email.item_metadata
                if metadata.get("from"):
                    lines.append(f"From: {metadata['from']}")
                if metadata.get("to"):
                    lines.append(f"To: {metadata['to']}")
                if metadata.get("date"):
                    lines.append(f"Date: {metadata['date']}")
            
            # Source timestamp
            if email.source_timestamp:
                lines.append(f"Timestamp: {email.source_timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            
            # Content
            lines.append("")
            if email.content:
                # Remove "From: ..." prefix if it's already in metadata
                content = email.content
                if content.startswith("From:") and email.item_metadata and email.item_metadata.get("from"):
                    # Skip the "From: ..." line if it's redundant
                    lines_split = content.split("\n", 1)
                    if len(lines_split) > 1:
                        content = lines_split[1].strip()
                    else:
                        content = content
                
                lines.append("Content:")
                lines.append(content)
            
            lines.append("")
            lines.append("=" * 80)
            lines.append("")
        
        # Create text file content
        text_content = "\n".join(lines)
        
        # Return as downloadable text file
        response = Response(
            text_content,
            mimetype='text/plain',
            headers={
                'Content-Disposition': f'attachment; filename=emails_export_{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")}.txt'
            }
        )
        return response
        
    except Exception as e:
        logger.error(f"Error exporting emails: {e}", exc_info=True)
        return jsonify({"error": f"Error exporting emails: {str(e)}"}), 500
    finally:
        db.close()


@bp.route("/whoop", methods=["GET"])
@login_required
def export_whoop():
    """Export all imported WHOOP health data to a text file for ChatGPT knowledge upload."""
    db = SessionLocal()
    try:
        # Query all WHOOP data items for this user
        whoop_items = db.query(DataItem).filter(
            DataItem.user_id == current_user.id,
            DataItem.plugin_name == "whoop"
        ).order_by(DataItem.source_timestamp.desc()).all()
        
        if not whoop_items:
            return jsonify({"error": "No WHOOP data found to export"}), 404
        
        # Group by type for better organization
        recovery_items = [item for item in whoop_items if item.item_type == "whoop_recovery"]
        sleep_items = [item for item in whoop_items if item.item_type == "whoop_sleep"]
        workout_items = [item for item in whoop_items if item.item_type == "whoop_workout"]
        
        # Format WHOOP data for ChatGPT knowledge upload
        lines = []
        lines.append("=" * 80)
        lines.append("WHOOP HEALTH DATA EXPORT FOR CHATGPT KNOWLEDGE")
        lines.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        lines.append(f"Total Items: {len(whoop_items)}")
        lines.append(f"  - Recovery Records: {len(recovery_items)}")
        lines.append(f"  - Sleep Records: {len(sleep_items)}")
        lines.append(f"  - Workout Records: {len(workout_items)}")
        lines.append("=" * 80)
        lines.append("")
        
        # Export Recovery Data
        if recovery_items:
            lines.append("=" * 80)
            lines.append("RECOVERY DATA")
            lines.append("=" * 80)
            lines.append("")
            for idx, item in enumerate(sorted(recovery_items, key=lambda x: x.source_timestamp or datetime.min.replace(tzinfo=timezone.utc)), 1):
                lines.append(f"RECOVERY #{idx}")
                lines.append("-" * 80)
                
                if item.title:
                    lines.append(item.title)
                
                if item.source_timestamp:
                    lines.append(f"Date: {item.source_timestamp.strftime('%Y-%m-%d')}")
                
                if item.item_metadata:
                    metadata = item.item_metadata
                    if metadata.get("recovery_score") is not None:
                        lines.append(f"Recovery Score: {metadata['recovery_score']}")
                    if metadata.get("resting_heart_rate") is not None:
                        lines.append(f"Resting Heart Rate: {metadata['resting_heart_rate']} bpm")
                    if metadata.get("hrv") is not None:
                        lines.append(f"HRV: {metadata['hrv']} ms")
                
                if item.content:
                    lines.append("")
                    lines.append("Details:")
                    lines.append(item.content)
                
                lines.append("")
                lines.append("-" * 80)
                lines.append("")
        
        # Export Sleep Data
        if sleep_items:
            lines.append("=" * 80)
            lines.append("SLEEP DATA")
            lines.append("=" * 80)
            lines.append("")
            for idx, item in enumerate(sorted(sleep_items, key=lambda x: x.source_timestamp or datetime.min.replace(tzinfo=timezone.utc)), 1):
                lines.append(f"SLEEP #{idx}")
                lines.append("-" * 80)
                
                if item.title:
                    lines.append(item.title)
                
                if item.source_timestamp:
                    lines.append(f"Date: {item.source_timestamp.strftime('%Y-%m-%d')}")
                
                if item.item_metadata:
                    metadata = item.item_metadata
                    if metadata.get("sleep_score") is not None:
                        lines.append(f"Sleep Score: {metadata['sleep_score']}")
                    if metadata.get("total_sleep_ms") is not None:
                        hours = metadata['total_sleep_ms'] / 3600000
                        lines.append(f"Total Sleep: {hours:.2f} hours")
                    if metadata.get("sleep_efficiency") is not None:
                        lines.append(f"Sleep Efficiency: {metadata['sleep_efficiency']}%")
                
                if item.content:
                    lines.append("")
                    lines.append("Details:")
                    lines.append(item.content)
                
                lines.append("")
                lines.append("-" * 80)
                lines.append("")
        
        # Export Workout/Strain Data
        if workout_items:
            lines.append("=" * 80)
            lines.append("WORKOUT / STRAIN DATA")
            lines.append("=" * 80)
            lines.append("")
            for idx, item in enumerate(sorted(workout_items, key=lambda x: x.source_timestamp or datetime.min.replace(tzinfo=timezone.utc)), 1):
                lines.append(f"WORKOUT #{idx}")
                lines.append("-" * 80)
                
                if item.title:
                    lines.append(item.title)
                
                if item.source_timestamp:
                    lines.append(f"Date: {item.source_timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
                
                if item.item_metadata:
                    metadata = item.item_metadata
                    if metadata.get("strain_score") is not None:
                        lines.append(f"Strain Score: {metadata['strain_score']}")
                    if metadata.get("sport_id"):
                        lines.append(f"Sport ID: {metadata['sport_id']}")
                
                if item.content:
                    lines.append("")
                    lines.append("Details:")
                    lines.append(item.content)
                
                lines.append("")
                lines.append("-" * 80)
                lines.append("")
        
        # Create text file content
        text_content = "\n".join(lines)
        
        # Return as downloadable text file
        response = Response(
            text_content,
            mimetype='text/plain',
            headers={
                'Content-Disposition': f'attachment; filename=whoop_export_{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")}.txt'
            }
        )
        return response
        
    except Exception as e:
        logger.error(f"Error exporting WHOOP data: {e}", exc_info=True)
        return jsonify({"error": f"Error exporting WHOOP data: {str(e)}"}), 500
    finally:
        db.close()

