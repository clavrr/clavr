"""
API Key Authentication

Provides API key-based authentication for programmatic access.
API keys are stored as SHA-256 hashes with scopes for fine-grained permissions.
"""
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON, ForeignKey, Index
from sqlalchemy.orm import relationship, Session
from fastapi import Request, HTTPException, status, Depends, Header
from fastapi.security import APIKeyHeader

from ..database.models import Base, User
from ..utils.security import generate_api_key as generate_secure_key, hash_token, verify_token
from ..utils.logger import setup_logger
from .audit import log_auth_event, AuditEventType

logger = setup_logger(__name__)

# API Key header scheme
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class APIKey(Base):
    """
    API Key model for programmatic access.
    
    Features:
    - Hashed storage (raw key only shown once on creation)
    - Scopes for fine-grained permissions
    - Expiration dates
    - Usage tracking
    - Last used timestamp
    """
    __tablename__ = 'api_keys'
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    
    # Key storage (SHA-256 hash, never store raw key)
    key_hash = Column(String(64), unique=True, nullable=False, index=True)
    key_prefix = Column(String(12), nullable=False)  # First 8 chars for identification (e.g., "sk_abc123")
    
    # Metadata
    name = Column(String(100), nullable=False)  # User-defined name
    description = Column(String(500))  # Optional description
    
    # Permissions
    scopes = Column(JSON, default=list)  # List of allowed scopes
    
    # Usage tracking
    last_used_at = Column(DateTime, nullable=True)
    last_used_ip = Column(String(45), nullable=True)  # IPv4/IPv6
    usage_count = Column(Integer, default=0)
    
    # Lifecycle
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=True, index=True)  # None = never expires
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    revoked_at = Column(DateTime, nullable=True)
    revoked_reason = Column(String(200), nullable=True)
    
    # Relationship
    user = relationship("User", backref="api_keys")
    
    # Indexes for common queries
    __table_args__ = (
        Index('idx_apikey_user_active', 'user_id', 'is_active'),
        Index('idx_apikey_hash_active', 'key_hash', 'is_active'),
    )
    
    def is_expired(self) -> bool:
        """Check if API key is expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at
    
    def is_valid(self) -> bool:
        """Check if API key is valid (active and not expired)."""
        return self.is_active and not self.is_expired()
    
    def has_scope(self, scope: str) -> bool:
        """Check if API key has a specific scope."""
        if not self.scopes:
            return False
        # Support wildcard scopes
        if "*" in self.scopes:
            return True
        if scope in self.scopes:
            return True
        # Check partial matches (e.g., "read:*" matches "read:emails")
        scope_parts = scope.split(":")
        for s in self.scopes:
            s_parts = s.split(":")
            if len(s_parts) == 2 and s_parts[1] == "*" and s_parts[0] == scope_parts[0]:
                return True
        return False
    
    def to_dict(self) -> dict:
        """Convert to dictionary (for API responses)."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "key_prefix": self.key_prefix,
            "scopes": self.scopes,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "usage_count": self.usage_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "is_active": self.is_active,
        }
    
    def __repr__(self):
        return f"<APIKey(id={self.id}, name='{self.name}', prefix='{self.key_prefix}')>"


# Available scopes
class APIScopes:
    """Available API scopes for fine-grained permissions."""
    
    # Read scopes
    READ_EMAILS = "read:emails"
    READ_CALENDAR = "read:calendar"
    READ_TASKS = "read:tasks"
    READ_PROFILE = "read:profile"
    READ_ALL = "read:*"
    
    # Write scopes
    WRITE_EMAILS = "write:emails"
    WRITE_CALENDAR = "write:calendar"
    WRITE_TASKS = "write:tasks"
    WRITE_PROFILE = "write:profile"
    WRITE_ALL = "write:*"
    
    # Admin scopes
    ADMIN = "admin"
    
    # Full access
    FULL_ACCESS = "*"
    
    @classmethod
    def all_scopes(cls) -> List[str]:
        """Get all available scopes."""
        return [
            cls.READ_EMAILS, cls.READ_CALENDAR, cls.READ_TASKS, cls.READ_PROFILE,
            cls.WRITE_EMAILS, cls.WRITE_CALENDAR, cls.WRITE_TASKS, cls.WRITE_PROFILE,
            cls.ADMIN, cls.FULL_ACCESS
        ]


async def create_api_key(
    db: Session,
    user_id: int,
    name: str,
    scopes: Optional[List[str]] = None,
    description: Optional[str] = None,
    expires_in_days: Optional[int] = None,
    request: Optional[Request] = None
) -> Tuple[str, APIKey]:
    """
    Create a new API key.
    
    Args:
        db: Database session
        user_id: User ID
        name: User-defined name for the key
        scopes: List of permission scopes
        description: Optional description
        expires_in_days: Days until expiration (None = never)
        request: Request object for audit logging
        
    Returns:
        (raw_key, api_key_record) - raw_key is only available at creation time
    """
    # Generate secure key
    raw_key, key_hash = generate_secure_key(prefix="clavr")
    key_prefix = raw_key[:12]  # Store first 12 chars for identification
    
    # Set expiration
    expires_at = None
    if expires_in_days:
        expires_at = datetime.utcnow() + timedelta(days=expires_in_days)
    
    # Create API key record
    api_key = APIKey(
        user_id=user_id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=name,
        description=description,
        scopes=scopes or [APIScopes.READ_ALL],  # Default to read-only
        expires_at=expires_at
    )
    
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    
    # Log creation
    await log_auth_event(
        db=db,
        event_type="api_key_created",
        user_id=user_id,
        success=True,
        request=request,
        key_id=api_key.id,
        key_name=name,
        scopes=scopes
    )
    
    logger.info(f"Created API key '{name}' for user {user_id}")
    
    return raw_key, api_key


async def verify_api_key(
    db: Session,
    raw_key: str,
    required_scope: Optional[str] = None,
    request: Optional[Request] = None
) -> Optional[APIKey]:
    """
    Verify an API key and check scope.
    
    Args:
        db: Database session
        raw_key: Raw API key from request
        required_scope: Required scope (optional)
        request: Request object for usage tracking
        
    Returns:
        APIKey record if valid, None otherwise
    """
    if not raw_key:
        return None
    
    # Hash the key to find it
    key_hash = hash_token(raw_key)
    
    # Query for the key
    api_key = db.query(APIKey).filter(
        APIKey.key_hash == key_hash,
        APIKey.is_active == True
    ).first()
    
    if not api_key:
        logger.warning(f"API key not found or inactive: {raw_key[:12]}...")
        return None
    
    # Check expiration
    if api_key.is_expired():
        logger.warning(f"API key expired: {api_key.name}")
        return None
    
    # Check scope
    if required_scope and not api_key.has_scope(required_scope):
        logger.warning(f"API key '{api_key.name}' missing scope: {required_scope}")
        return None
    
    # Update usage stats
    api_key.last_used_at = datetime.utcnow()
    api_key.usage_count += 1
    
    if request:
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            api_key.last_used_ip = forwarded_for.split(",")[0].strip()
        elif request.client:
            api_key.last_used_ip = request.client.host
    
    db.commit()
    
    return api_key


async def revoke_api_key(
    db: Session,
    key_id: int,
    user_id: int,
    reason: Optional[str] = None,
    request: Optional[Request] = None
) -> bool:
    """
    Revoke an API key.
    
    Args:
        db: Database session
        key_id: API key ID
        user_id: User ID (for authorization)
        reason: Reason for revocation
        request: Request object for audit logging
        
    Returns:
        True if revoked, False if not found
    """
    api_key = db.query(APIKey).filter(
        APIKey.id == key_id,
        APIKey.user_id == user_id
    ).first()
    
    if not api_key:
        return False
    
    api_key.is_active = False
    api_key.revoked_at = datetime.utcnow()
    api_key.revoked_reason = reason
    
    db.commit()
    
    # Log revocation
    await log_auth_event(
        db=db,
        event_type="api_key_revoked",
        user_id=user_id,
        success=True,
        request=request,
        key_id=key_id,
        key_name=api_key.name,
        reason=reason
    )
    
    logger.info(f"Revoked API key '{api_key.name}' for user {user_id}")
    
    return True


def list_api_keys(db: Session, user_id: int, include_revoked: bool = False) -> List[APIKey]:
    """
    List API keys for a user.
    
    Args:
        db: Database session
        user_id: User ID
        include_revoked: Whether to include revoked keys
        
    Returns:
        List of API keys
    """
    query = db.query(APIKey).filter(APIKey.user_id == user_id)
    
    if not include_revoked:
        query = query.filter(APIKey.is_active == True)
    
    return query.order_by(APIKey.created_at.desc()).all()


# FastAPI dependency for API key authentication
async def get_api_key_user(
    request: Request,
    api_key: Optional[str] = Depends(api_key_header)
) -> Optional[User]:
    """
    FastAPI dependency to authenticate via API key.
    
    Usage:
        @app.get("/api/data")
        async def get_data(user: User = Depends(get_api_key_user)):
            if not user:
                raise HTTPException(401)
            return {"user_id": user.id}
    """
    if not api_key:
        return None
    
    from ..database import get_db
    
    db = next(get_db())
    try:
        api_key_record = await verify_api_key(db, api_key, request=request)
        
        if api_key_record:
            return api_key_record.user
        
        return None
    finally:
        db.close()


def require_api_key(required_scope: Optional[str] = None):
    """
    FastAPI dependency factory that requires a valid API key.
    
    Usage:
        @app.get("/api/emails")
        async def get_emails(user: User = Depends(require_api_key("read:emails"))):
            return {"emails": [...]}
    """
    async def dependency(
        request: Request,
        api_key: Optional[str] = Depends(api_key_header)
    ) -> User:
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key required",
                headers={"WWW-Authenticate": "X-API-Key"}
            )
        
        from ..database import get_db
        
        db = next(get_db())
        try:
            api_key_record = await verify_api_key(
                db, api_key, required_scope=required_scope, request=request
            )
            
            if not api_key_record:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired API key",
                    headers={"WWW-Authenticate": "X-API-Key"}
                )
            
            if required_scope and not api_key_record.has_scope(required_scope):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"API key missing required scope: {required_scope}"
                )
            
            return api_key_record.user
        finally:
            db.close()
    
    return dependency
