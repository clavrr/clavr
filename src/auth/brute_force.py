"""
Brute Force Protection

Provides enhanced protection against brute force attacks with:
- Account lockout after failed attempts
- Progressive delays
- IP-based blocking
- Attack pattern detection
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..database.models import AuditLog
from .audit import log_auth_event, AuditEventType, get_failed_login_attempts
from ..utils.logger import setup_logger

logger = setup_logger(__name__)


# Configuration
MAX_FAILED_ATTEMPTS = 5  # Lock after 5 failed attempts
LOCKOUT_DURATION_MINUTES = 30  # Lock for 30 minutes
PROGRESSIVE_DELAY_ENABLED = True  # Add delays after failed attempts
PROGRESSIVE_DELAY_BASE_SECONDS = 1  # Base delay (doubles each attempt)
MAX_DELAY_SECONDS = 30  # Maximum delay cap


class BruteForceProtection:
    """
    Brute force attack protection service.
    
    Features:
    - Account lockout after MAX_FAILED_ATTEMPTS
    - Progressive delays between attempts
    - IP-based blocking
    - Pattern detection for distributed attacks
    """
    
    def __init__(
        self,
        max_attempts: int = MAX_FAILED_ATTEMPTS,
        lockout_minutes: int = LOCKOUT_DURATION_MINUTES,
        enable_delays: bool = PROGRESSIVE_DELAY_ENABLED
    ):
        self.max_attempts = max_attempts
        self.lockout_minutes = lockout_minutes
        self.enable_delays = enable_delays
        
        # In-memory cache for quick lookups (supplement to database)
        self._lockout_cache: Dict[str, datetime] = {}
        self._attempt_cache: Dict[str, int] = {}
    
    async def check_login_allowed(
        self,
        db: Session,
        identifier: str,
        identifier_type: str = "email"
    ) -> Tuple[bool, Optional[str], Optional[int]]:
        """
        Check if login attempt is allowed.
        
        Args:
            db: Database session
            identifier: Email address or IP address
            identifier_type: "email" or "ip"
            
        Returns:
            (is_allowed, reason, retry_after_seconds)
        """
        # Check in-memory cache first (fast path)
        cache_key = f"{identifier_type}:{identifier}"
        
        if cache_key in self._lockout_cache:
            lockout_until = self._lockout_cache[cache_key]
            if datetime.utcnow() < lockout_until:
                remaining = int((lockout_until - datetime.utcnow()).total_seconds())
                return False, f"Account locked. Try again in {remaining // 60} minutes.", remaining
            else:
                # Lockout expired, remove from cache
                del self._lockout_cache[cache_key]
                if cache_key in self._attempt_cache:
                    del self._attempt_cache[cache_key]
        
        # Check database for recent failures
        if identifier_type == "ip":
            failures = get_failed_login_attempts(
                db,
                ip_address=identifier,
                hours=self.lockout_minutes / 60
            )
        else:
            # For email, we need to query by event_data
            cutoff_time = datetime.utcnow() - timedelta(minutes=self.lockout_minutes)
            failures = db.query(AuditLog).filter(
                AuditLog.event_type == AuditEventType.LOGIN_FAILURE,
                AuditLog.created_at >= cutoff_time,
                AuditLog.success == False
            ).all()
            # Filter by email in event_data
            failures = [f for f in failures if f.event_data and f.event_data.get('email') == identifier]
        
        attempt_count = len(failures)
        
        if attempt_count >= self.max_attempts:
            # Lock the account
            lockout_until = datetime.utcnow() + timedelta(minutes=self.lockout_minutes)
            self._lockout_cache[cache_key] = lockout_until
            
            logger.warning(
                f"Account locked due to {attempt_count} failed attempts: {identifier}"
            )
            
            return (
                False,
                f"Account locked due to too many failed attempts. Try again in {self.lockout_minutes} minutes.",
                self.lockout_minutes * 60
            )
        
        # Apply progressive delay if enabled
        if self.enable_delays and attempt_count > 0:
            delay = min(
                PROGRESSIVE_DELAY_BASE_SECONDS * (2 ** (attempt_count - 1)),
                MAX_DELAY_SECONDS
            )
            await asyncio.sleep(delay)
        
        return True, None, None
    
    async def record_failed_attempt(
        self,
        db: Session,
        identifier: str,
        identifier_type: str = "email",
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        error_message: Optional[str] = None
    ):
        """
        Record a failed login attempt.
        
        Args:
            db: Database session
            identifier: Email or username
            identifier_type: Type of identifier
            ip_address: Client IP address
            user_agent: Client user agent
            error_message: Reason for failure
        """
        cache_key = f"{identifier_type}:{identifier}"
        
        # Update in-memory counter
        self._attempt_cache[cache_key] = self._attempt_cache.get(cache_key, 0) + 1
        
        # Log to audit trail
        event_data = {
            identifier_type: identifier,
            'attempt_count': self._attempt_cache[cache_key]
        }
        
        # Create audit log entry directly since we don't have a request object
        audit_log = AuditLog(
            user_id=None,  # No user yet
            event_type=AuditEventType.LOGIN_FAILURE,
            event_data=event_data,
            ip_address=ip_address,
            user_agent=user_agent,
            success=False,
            error_message=error_message
        )
        
        db.add(audit_log)
        db.commit()
        
        logger.info(
            f"Failed login attempt recorded: {identifier} "
            f"(attempt #{self._attempt_cache[cache_key]})"
        )
    
    async def record_successful_login(
        self,
        db: Session,
        identifier: str,
        identifier_type: str = "email"
    ):
        """
        Record a successful login and clear lockout state.
        
        Args:
            db: Database session
            identifier: Email or username
            identifier_type: Type of identifier
        """
        cache_key = f"{identifier_type}:{identifier}"
        
        # Clear from caches
        if cache_key in self._lockout_cache:
            del self._lockout_cache[cache_key]
        if cache_key in self._attempt_cache:
            del self._attempt_cache[cache_key]
        
        logger.info(f"Successful login cleared lockout state: {identifier}")
    
    def get_remaining_attempts(
        self,
        db: Session,
        identifier: str,
        identifier_type: str = "email"
    ) -> int:
        """
        Get remaining login attempts before lockout.
        
        Args:
            db: Database session
            identifier: Email or IP
            identifier_type: Type of identifier
            
        Returns:
            Number of remaining attempts
        """
        cache_key = f"{identifier_type}:{identifier}"
        current_attempts = self._attempt_cache.get(cache_key, 0)
        return max(0, self.max_attempts - current_attempts)
    
    def detect_distributed_attack(
        self,
        db: Session,
        time_window_minutes: int = 10,
        threshold: int = 100
    ) -> bool:
        """
        Detect distributed brute force attack patterns.
        
        Checks for high volume of failed logins across different IPs
        targeting the same or few accounts.
        
        Args:
            db: Database session
            time_window_minutes: Time window to analyze
            threshold: Number of failures to trigger alert
            
        Returns:
            True if attack pattern detected
        """
        cutoff_time = datetime.utcnow() - timedelta(minutes=time_window_minutes)
        
        # Count total failures in window
        total_failures = db.query(func.count(AuditLog.id)).filter(
            AuditLog.event_type == AuditEventType.LOGIN_FAILURE,
            AuditLog.created_at >= cutoff_time
        ).scalar()
        
        if total_failures >= threshold:
            # Count unique IPs
            unique_ips = db.query(func.count(func.distinct(AuditLog.ip_address))).filter(
                AuditLog.event_type == AuditEventType.LOGIN_FAILURE,
                AuditLog.created_at >= cutoff_time
            ).scalar()
            
            # If many failures from many IPs, likely distributed attack
            if unique_ips >= threshold * 0.5:  # At least 50% unique IPs
                logger.warning(
                    f"Distributed attack detected: {total_failures} failures "
                    f"from {unique_ips} unique IPs in {time_window_minutes} minutes"
                )
                return True
        
        return False


# Singleton instance
_brute_force_protection: Optional[BruteForceProtection] = None


def get_brute_force_protection() -> BruteForceProtection:
    """Get the singleton brute force protection instance."""
    global _brute_force_protection
    
    if _brute_force_protection is None:
        _brute_force_protection = BruteForceProtection()
    
    return _brute_force_protection
