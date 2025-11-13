"""Database models and connection."""
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, JSON
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
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    records_imported = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    metadata = Column(JSON, nullable=True)


class DataItem(Base):
    """Stored data items from various sources."""
    __tablename__ = "data_items"
    
    id = Column(Integer, primary_key=True)
    plugin_name = Column(String(100), nullable=False, index=True)
    source_id = Column(String(255), nullable=False)  # Unique ID from source
    item_type = Column(String(50), nullable=False)  # email, todo, health_data, calendar_event, etc.
    title = Column(String(500), nullable=True)
    content = Column(Text, nullable=True)
    metadata = Column(JSON, nullable=True)  # Additional structured data
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    source_timestamp = Column(DateTime, nullable=True)  # Original timestamp from source
    
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


def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

