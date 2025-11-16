"""Database models and connection."""
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, JSON, LargeBinary, ForeignKey, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from flask_login import UserMixin
import config

Base = declarative_base()


class User(UserMixin, Base):
    """User model for authentication."""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="regular")  # admin or regular
    active = Column(Integer, nullable=False, default=0)  # 0 = inactive, 1 = active (for approval)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    def is_active(self):
        """Check if user account is active (approved)."""
        return self.active == 1
    
    def is_admin(self):
        """Check if user is an admin."""
        return self.role == "admin"


class ImportLog(Base):
    """Log of data imports."""
    __tablename__ = "import_logs"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
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
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
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
    
    # Unique constraint on user_id + plugin_name + source_id
    __table_args__ = (
        {'sqlite_autoincrement': True},
    )


class ChatThread(Base):
    """Chat thread model for persisting conversations."""
    __tablename__ = "chat_threads"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    thread_id = Column(String(255), nullable=False, unique=True, index=True)  # OpenAI thread ID
    title = Column(String(500), nullable=True)  # Optional title (first message or user-defined)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class UserSettings(Base):
    """User settings model for storing user preferences."""
    __tablename__ = "user_settings"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, unique=True, index=True)
    assistant_instructions = Column(Text, nullable=True)  # Custom AI assistant instructions
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class PluginConfiguration(Base):
    """Plugin configuration model for storing user-specific plugin settings."""
    __tablename__ = "plugin_configurations"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    plugin_name = Column(String(100), nullable=False, index=True)
    config_data = Column(JSON, nullable=False)  # JSON object with plugin-specific configuration
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Unique constraint on user_id + plugin_name
    __table_args__ = (
        UniqueConstraint('user_id', 'plugin_name', name='uq_plugin_config_user_plugin'),
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

