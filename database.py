"""Database models and connection."""
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, JSON, LargeBinary
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import config

Base = declarative_base()


class ImportLog(Base):
    """Log of data imports."""
    __tablename__ = "import_logs"
    
    id = Column(Integer, primary_key=True)
    plugin_name = Column(String(100), nullable=False, index=True)
    status = Column(String(20), nullable=False)  # success, error, running
    started_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)
    records_imported = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    log_metadata = Column(JSON, nullable=True)  # Renamed from 'metadata' to avoid SQLAlchemy conflict
    progress_current = Column(Integer, default=0)  # Current progress (e.g., emails processed)
    progress_total = Column(Integer, default=0)  # Total items to process
    progress_message = Column(String(500), nullable=True)  # Current status message


class DataItem(Base):
    """Stored data items from various sources."""
    __tablename__ = "data_items"
    
    id = Column(Integer, primary_key=True)
    plugin_name = Column(String(100), nullable=False, index=True)
    source_id = Column(String(255), nullable=False)  # Unique ID from source
    item_type = Column(String(50), nullable=False)  # email, todo, health_data, calendar_event, etc.
    title = Column(String(500), nullable=True)
    content = Column(Text, nullable=True)
    item_metadata = Column(JSON, nullable=True)  # Additional structured data (renamed from 'metadata' to avoid SQLAlchemy conflict)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    source_timestamp = Column(DateTime, nullable=True)  # Original timestamp from source
    embedding = Column(LargeBinary, nullable=True)  # Deprecated: kept for backward compatibility (no longer used)
    
    # Unique constraint on plugin_name + source_id
    __table_args__ = (
        {'sqlite_autoincrement': True},
    )


# Database engine and session
engine = create_engine(f"sqlite:///{config.DATABASE_PATH}", echo=False, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Initialize the database tables."""
    Base.metadata.create_all(bind=engine)
    # Run migration to add new columns if needed
    try:
        from migrate_db import migrate_database
        migrate_database()
    except Exception as e:
        # Migration is optional - if it fails, the app can still run
        # (columns might already exist or migration script might not be available)
        pass


def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

