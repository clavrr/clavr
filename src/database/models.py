"""
SQLAlchemy models for multi-user authentication and settings
"""
from datetime import datetime, timedelta
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, JSON, Index, Float
from sqlalchemy.orm import DeclarativeBase, relationship

class Base(DeclarativeBase):
    pass


class User(Base):
    """User model for authentication"""
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True, index=True)
    google_id = Column(String(255), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255))
    picture_url = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)  # Indexed for analytics
    
    # Email indexing tracking (legacy fields - kept for backward compatibility)
    email_indexed = Column(Boolean, default=False, index=True)  # Indexed for stats queries
    index_count = Column(Integer, default=0)
    indexing_status = Column(String(50), default='not_started', index=True)  # Indexed for status filtering
    indexing_started_at = Column(DateTime)
    indexing_completed_at = Column(DateTime)
    last_email_synced_at = Column(DateTime, index=True)  # Indexed for incremental sync queries
    collection_name = Column(String(255))  # User's vector store collection name
    
    # Smart indexing fields (NEW)
    last_indexed_timestamp = Column(DateTime, nullable=True, index=True)  # Last successful index timestamp
    initial_indexing_complete = Column(Boolean, default=False, index=True)  # First-time indexing done
    indexing_date_range_start = Column(DateTime, nullable=True)  # Start of indexed date range
    total_emails_indexed = Column(Integer, default=0)  # Total count of indexed emails
    indexing_progress_percent = Column(Float, default=0.0)  # Progress indicator (0-100)
    
    # Admin access
    is_admin = Column(Boolean, default=False, nullable=False, index=True)
    
    # Relationships
    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")
    settings = relationship("UserSettings", back_populates="user", uselist=False, cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<User(id={self.id}, email='{self.email}')>"


class Session(Base):
    """
    Session model for authentication tokens
    
    Security Note:
        session_token is stored as a SHA-256 hash (64 chars)
        The raw token is sent to the client but never stored in the database
    """
    __tablename__ = 'sessions'
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    session_token = Column(String(255), unique=True, nullable=False, index=True)  # Stores SHA-256 hash (64 chars)
    gmail_access_token = Column(Text)
    gmail_refresh_token = Column(Text)
    token_expiry = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)  # Indexed for session history
    expires_at = Column(DateTime, default=lambda: datetime.utcnow() + timedelta(days=7), index=True)  # Indexed for cleanup
    
    # Relationship
    user = relationship("User", back_populates="sessions")
    
    # Indexes for common queries
    __table_args__ = (
        Index('idx_sessions_user_expires', 'user_id', 'expires_at'),  # Composite for user session lookups
    )
    
    def is_expired(self) -> bool:
        """Check if session is expired"""
        return datetime.utcnow() > self.expires_at
    
    def __repr__(self):
        return f"<Session(id={self.id}, user_id={self.user_id})>"


class AuditLog(Base):
    """
    Audit log for security and authentication events
    
    Tracks all authentication-related events for security monitoring,
    compliance (GDPR, SOC 2), and forensic analysis.
    """
    __tablename__ = 'audit_logs'
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    event_type = Column(String(50), nullable=False, index=True)
    event_data = Column(JSON)
    ip_address = Column(String(45))  # IPv4/IPv6
    user_agent = Column(String(500))
    success = Column(Boolean, default=True, index=True)
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Relationship
    user = relationship("User")
    
    # Composite indexes for common queries
    __table_args__ = (
        Index('idx_audit_user_event_time', 'user_id', 'event_type', 'created_at'),
        Index('idx_audit_event_success_time', 'event_type', 'success', 'created_at'),
        Index('idx_audit_ip_time', 'ip_address', 'created_at'),
    )
    
    def __repr__(self):
        return f"<AuditLog(id={self.id}, event_type='{self.event_type}', user_id={self.user_id})>"


class ConversationMessage(Base):
    """Store conversation messages for context tracking"""
    __tablename__ = 'conversation_messages'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    session_id = Column(String(255), nullable=False, index=True)
    
    role = Column(String(50), nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    
    # Metadata from query router
    intent = Column(String(100))
    entities = Column(JSON)  # Extracted entities
    confidence = Column(String(20))  # confidence score as string
    
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    __table_args__ = (
        Index('idx_user_session_time', 'user_id', 'session_id', 'timestamp'),
    )
    
    def __repr__(self):
        return f"<ConversationMessage(id={self.id}, user_id={self.user_id}, role='{self.role}', content='{self.content[:50]}...')>"


class BlogPost(Base):
    """Blog post model for content management"""
    __tablename__ = 'blog_posts'
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Core content
    title = Column(String(500), nullable=False)  # Main blog post title
    slug = Column(String(500), unique=True, nullable=False, index=True)  # URL-friendly identifier
    description = Column(Text)  # Subtitle/lead paragraph (shown below title, before content)
    content = Column(Text, nullable=False)  # Full blog post content (markdown or HTML)
    # Content supports: headings (# ## ###), bold (**text**), italic (*text*), 
    # lists (-, *, 1.), code blocks (```code```), links [text](url), paragraphs, HTML tags
    
    # Metadata
    category = Column(String(100), nullable=False, index=True)  # e.g., "Product", "Engineering", "Company"
    author_id = Column(Integer, ForeignKey('users.id'), nullable=True)  # Optional: link to User
    featured_image_url = Column(Text)  # Optional: URL to featured image
    
    # Publishing
    is_published = Column(Boolean, default=False, index=True)
    published_at = Column(DateTime, nullable=True, index=True)
    
    # SEO & Analytics
    meta_title = Column(String(500))  # SEO title (can differ from display title)
    meta_description = Column(Text)  # SEO description
    tags = Column(JSON)  # Array of tags: ["ai", "productivity", "email"]
    
    # Read time estimation (in minutes)
    read_time_minutes = Column(Integer, default=0)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    author = relationship("User", foreign_keys=[author_id])
    
    __table_args__ = (
        Index('idx_blog_published', 'is_published', 'published_at'),
        Index('idx_blog_category_published', 'category', 'is_published'),
    )
    
    def __repr__(self):
        return f"<BlogPost(id={self.id}, title='{self.title[:50]}...', slug='{self.slug}')>"


class UserSettings(Base):
    """User preferences and settings"""
    __tablename__ = 'user_settings'
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), unique=True, nullable=False, index=True)
    
    # Notifications
    email_notifications = Column(Boolean, default=False, nullable=False)
    push_notifications = Column(Boolean, default=False, nullable=False)
    
    # Appearance
    dark_mode = Column(Boolean, default=True, nullable=False)  # Default to dark mode
    
    # Language & Region
    language = Column(String(10), default='en', nullable=False)  # ISO 639-1 language code (e.g., 'en', 'es', 'fr')
    region = Column(String(10), default='US', nullable=False)  # ISO 3166-1 alpha-2 country code (e.g., 'US', 'GB', 'CA')
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationship
    user = relationship("User", back_populates="settings")
    
    def __repr__(self):
        return f"<UserSettings(id={self.id}, user_id={self.user_id}, dark_mode={self.dark_mode})>"


class UserWritingProfile(Base):
    """
    User's email writing style profile
    
    Stores analyzed patterns from sent emails including:
    - Writing style (tone, formality, length preferences)
    - Common greetings and closings
    - Response patterns
    - Frequently used phrases
    
    Used to personalize AI-generated email responses.
    """
    __tablename__ = 'user_writing_profiles'
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), unique=True, nullable=False, index=True)
    
    # Profile data (JSON from ProfileBuilder.build_profile())
    # Contains: writing_style, response_patterns, preferences, common_phrases
    profile_data = Column(JSON, nullable=False)
    
    # Metadata
    sample_size = Column(Integer, default=0)  # Number of emails analyzed
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_rebuilt_at = Column(DateTime)  # Last time profile was rebuilt
    
    # Quality indicators
    confidence_score = Column(Float)  # 0.0-1.0, based on sample size and consistency
    needs_refresh = Column(Boolean, default=False, index=True)  # Flag for background updates
    
    # Relationship
    user = relationship("User", backref="writing_profile")
    
    def __repr__(self):
        return f"<UserWritingProfile(user_id={self.user_id}, sample_size={self.sample_size}, confidence={self.confidence_score})>"


class OAuthState(Base):
    """
    OAuth state tracking for CSRF protection
    
    Stores OAuth state tokens in database instead of in-memory store.
    This ensures states persist across server restarts and work with multiple workers.
    """
    __tablename__ = 'oauth_states'
    
    id = Column(Integer, primary_key=True, index=True)
    state = Column(String(64), unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)  # States expire after 10 minutes
    used = Column(Boolean, default=False, nullable=False, index=True)
    
    # Composite index for common query pattern
    __table_args__ = (
        Index('idx_oauth_state_validity', 'state', 'used', 'expires_at'),
    )
    
    def __repr__(self):
        return f"<OAuthState(state='{self.state[:10]}...', used={self.used}, expires_at='{self.expires_at}')>"

