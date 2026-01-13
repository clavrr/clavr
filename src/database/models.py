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
    meeting_templates = relationship("MeetingTemplate", back_populates="user", cascade="all, delete-orphan")
    task_templates = relationship("TaskTemplate", back_populates="user", cascade="all, delete-orphan")
    email_templates = relationship("EmailTemplate", back_populates="user", cascade="all, delete-orphan")
    integrations = relationship("UserIntegration", back_populates="user", cascade="all, delete-orphan")

    
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
    granted_scopes = Column(Text, nullable=True)  # Comma-separated list of OAuth scopes granted by user
    token_expiry = Column(DateTime)
    last_active_at = Column(DateTime, default=datetime.utcnow, index=True)  # Track inactivity
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


class InteractionSession(Base):
    """
    Stores Gemini Interactions API session IDs for stateful conversations.
    
    Persists the previous_interaction_id for each user so that multi-turn
    conversations survive server restarts and work across multiple workers.
    
    Enhanced with context tracking for richer conversation awareness.
    """
    __tablename__ = 'interaction_sessions'
    
    user_id = Column(Integer, ForeignKey('users.id'), primary_key=True, index=True)
    interaction_id = Column(String(255), nullable=False)  # Gemini Interactions API ID
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, index=True)
    
    # Context tracking (NEW)
    session_context = Column(JSON, default={})  # Current conversation context (entities, preferences)
    active_topics = Column(JSON, default=[])    # Topics discussed in this session
    last_intent = Column(String(100))           # Last detected intent (e.g., "schedule_meeting")
    turn_count = Column(Integer, default=0)     # Number of conversation turns
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)  # Session start time
    
    # Session quality metrics
    avg_response_satisfaction = Column(Float, default=None)  # Average user satisfaction (0-1)
    escalation_count = Column(Integer, default=0)            # Times user escalated or expressed frustration
    
    # Relationship
    user = relationship("User")
    
    def __repr__(self):
        return f"<InteractionSession(user_id={self.user_id}, turns={self.turn_count}, interaction_id='{self.interaction_id[:20]}...')>"
    
    def record_turn(self, intent: str = None, topic: str = None):
        """Record a new conversation turn with optional intent and topic."""
        self.turn_count = (self.turn_count or 0) + 1
        self.updated_at = datetime.utcnow()
        
        if intent:
            self.last_intent = intent
            
        if topic and topic not in (self.active_topics or []):
            topics = self.active_topics or []
            topics.append(topic)
            self.active_topics = topics[-10:]  # Keep last 10 topics
            
    def update_context(self, key: str, value):
        """Update a key in the session context."""
        context = self.session_context or {}
        context[key] = value
        self.session_context = context
        
    def get_session_duration_minutes(self) -> int:
        """Get session duration in minutes."""
        if not self.started_at:
            return 0
        delta = datetime.utcnow() - self.started_at
        return int(delta.total_seconds() / 60)

class UserIntegration(Base):
    """
    Store per-user integration tokens (Slack, Notion, Asana, etc.)
    """
    __tablename__ = 'user_integrations'
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    provider = Column(String(50), nullable=False)  # 'slack', 'notion', 'asana'
    
    # Auth data
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    token_type = Column(String(50), default='Bearer')
    
    # Metadata (e.g., bot_user_id, workspace_id, scopes)
    # Note: 'metadata' is a reserved attribute in SQLAlchemy models (Base.metadata)
    # so we use 'meta_data' or 'integration_metadata'
    integration_metadata = Column(JSON, default={})
    
    # Active status (for soft disconnect/pause)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    user = relationship("User", back_populates="integrations")
    
    # Constraints & Indexes
    __table_args__ = (
        Index('idx_user_provider', 'user_id', 'provider', unique=True),
    )
    
    def __repr__(self):
        return f"<UserIntegration(user_id={self.user_id}, provider='{self.provider}')>"



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
    
    # Multi-Agent State (NEW)
    agent_plan = Column(JSON)  # Supervisor's execution plan
    execution_metadata = Column(JSON)  # Agent-specific metadata (tool calls, reasoning)
    active_agent = Column(String(50))  # Agent that handled the message
    
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


class AgentFact(Base):
    """
    Semantic Memory for agents (Fact Store).
    
    Stores discrete facts and preferences learned by agents about the user.
    Distinct from conversation logs, this is for structured, long-term knowledge.
    """
    __tablename__ = 'agent_facts'
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    
    content = Column(Text, nullable=False)  # The fact string (e.g. "Likes aisle seats")
    category = Column(String(50), index=True)  # preference, personal_detail, work_context, etc.
    source = Column(String(50))  # which agent or tool learned this
    confidence = Column(Float, default=1.0)
    
    # Vector embedding ID (if using external vector DB link)
    embedding_id = Column(String(255))
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationship
    # Relationship
    user = relationship("User", backref="facts")
    
    def __repr__(self):
        return f"<AgentFact(id={self.id}, content='{self.content[:50]}...')>"

class AgentGoal(Base):
    """
    Goal model for Autonomous Agent Planning.
    Stores high-level user goals that the agent should proactively work towards.
    """
    __tablename__ = 'agent_goals'
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    
    title = Column(String(255), nullable=False)
    description = Column(Text)
    status = Column(String(50), default='pending', index=True) # pending, active, completed, archived
    deadline = Column(DateTime, nullable=True)
    
    # Context tags (e.g. project name, key contact) to help Perception/Planner
    context_tags = Column(JSON, default=[]) # ["Project X", "Deep Work"]
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("User", backref="goals")
    
    # Index for common queries
    __table_args__ = (
        Index('idx_agent_goals_user_status', 'user_id', 'status'),
    )
    
    def __repr__(self):
        return f"<AgentGoal(id={self.id}, title='{self.title}', status='{self.status}')>"


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


class MeetingTemplate(Base):
    """
    Meeting template model for calendar events
    
    Stores reusable meeting templates that users can quickly apply when creating calendar events.
    """
    __tablename__ = 'meeting_templates'
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    title = Column(String(500))
    duration_minutes = Column(Integer, default=60)
    description = Column(Text)
    location = Column(String(500))
    default_attendees = Column(JSON)  # List of email addresses
    recurrence = Column(String(100))  # e.g., "DAILY", "WEEKLY", "MONTHLY", "YEARLY"
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    
    # Relationships
    user = relationship("User", back_populates="meeting_templates")
    
    # Unique constraint: user can't have duplicate template names
    __table_args__ = (
        Index('idx_template_user_name', 'user_id', 'name', unique=True),
        Index('idx_template_user_active', 'user_id', 'is_active'),
    )
    
    def __repr__(self):
        return f"<MeetingTemplate(id={self.id}, user_id={self.user_id}, name='{self.name}')>"
    
    def to_dict(self) -> dict:
        """Convert template to dictionary"""
        return {
            'id': self.id,
            'name': self.name,
            'title': self.title,
            'duration_minutes': self.duration_minutes,
            'description': self.description,
            'location': self.location,
            'default_attendees': self.default_attendees or [],
            'recurrence': self.recurrence,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'is_active': self.is_active
        }


class TaskTemplate(Base):
    """
    Task template model for reusable task templates
    
    Stores reusable task templates that support variable substitution.
    """
    __tablename__ = 'task_templates'
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(String(500))  # Template display name
    task_description = Column(Text, nullable=False)  # Task description (supports {variables})
    priority = Column(String(20), default='medium')  # 'low', 'medium', 'high'
    category = Column(String(100))  # e.g., 'work', 'personal', 'project'
    tags = Column(JSON)  # List of tags
    subtasks = Column(JSON)  # List of subtask descriptions
    recurrence = Column(String(100))  # e.g., 'daily', 'weekly', 'monthly'
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    
    # Relationships
    user = relationship("User", back_populates="task_templates")
    
    # Unique constraint: user can't have duplicate template names
    __table_args__ = (
        Index('idx_task_template_user_name', 'user_id', 'name', unique=True),
        Index('idx_task_template_user_active', 'user_id', 'is_active'),
    )
    
    def __repr__(self):
        return f"<TaskTemplate(id={self.id}, user_id={self.user_id}, name='{self.name}')>"
    
    def to_dict(self) -> dict:
        """Convert template to dictionary"""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'task_description': self.task_description,
            'priority': self.priority,
            'category': self.category,
            'tags': self.tags or [],
            'subtasks': self.subtasks or [],
            'recurrence': self.recurrence,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'is_active': self.is_active
        }


class EmailTemplate(Base):
    """
    Email template model for reusable email presets
    
    Stores reusable email templates that support variable substitution.
    """
    __tablename__ = 'email_templates'
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    subject = Column(String(500))  # Email subject (supports {variables})
    body = Column(Text, nullable=False)  # Email body (supports {variables})
    to_recipients = Column(JSON)  # Default recipients (list of email addresses)
    cc_recipients = Column(JSON)  # Default CC recipients
    bcc_recipients = Column(JSON)  # Default BCC recipients
    tone = Column(String(50), default='professional')  # 'professional', 'casual', 'friendly', 'formal'
    category = Column(String(100))  # e.g., 'followup', 'thankyou', 'meeting_request', 'introduction'
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    
    # Relationships
    user = relationship("User", back_populates="email_templates")
    
    # Unique constraint: user can't have duplicate template names
    __table_args__ = (
        Index('idx_email_template_user_name', 'user_id', 'name', unique=True),
        Index('idx_email_template_user_active', 'user_id', 'is_active'),
    )
    
    def __repr__(self):
        return f"<EmailTemplate(id={self.id}, user_id={self.user_id}, name='{self.name}')>"
    
    def to_dict(self) -> dict:
        """Convert template to dictionary"""
        return {
            'id': self.id,
            'name': self.name,
            'subject': self.subject,
            'body': self.body,
            'to_recipients': self.to_recipients or [],
            'cc_recipients': self.cc_recipients or [],
            'bcc_recipients': self.bcc_recipients or [],
            'tone': self.tone,
            'category': self.category,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'is_active': self.is_active
        }


class ActionableItem(Base):
    """
    Extracted actionable items for proactive reminders.
    
    Stores bills, appointments, deadlines, and other time-sensitive items
    extracted from unstructured sources like emails.
    """
    __tablename__ = 'actionable_items'
    
    id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), index=True)
    
    title = Column(String(500), nullable=False)
    item_type = Column(String(50))  # bill, appointment, deadline, task
    due_date = Column(DateTime, nullable=False, index=True)
    amount = Column(Float, nullable=True)
    source_type = Column(String(50))  # email, calendar, asana, notion, extracted
    source_id = Column(String(255))   # original item ID
    
    status = Column(String(50), default='pending', index=True)  # pending, reminded, completed, dismissed
    urgency = Column(String(20))     # high, medium, low
    suggested_action = Column(String(100)) # Pay, RSVP, Sign, Book
    
    extracted_at = Column(DateTime, default=datetime.utcnow)
    reminder_sent_at = Column(DateTime, nullable=True)
    
    # Relationship
    user = relationship("User", backref="actionable_items")
    
    __table_args__ = (
        Index('idx_actionable_user_status_due', 'user_id', 'status', 'due_date'),
    )
    
    def __repr__(self):
        return f"<ActionableItem(id={self.id}, title='{self.title[:30]}...', type={self.item_type})>"


