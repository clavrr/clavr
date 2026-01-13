"""
Security Audit Logger

Handles structured logging of security-relevant events.
Separates security logs from application logs to ensure auditability.
"""
import logging
import json
from datetime import datetime
from typing import Dict, Any, Optional
import os

# Create a dedicated logger for security events
audit_logger = logging.getLogger("security_audit")
audit_logger.setLevel(logging.INFO)

# Ensure logs directory exists
LOG_DIR = os.path.join(os.path.expanduser("~"), ".clavr", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# File handler for security events
file_handler = logging.FileHandler(os.path.join(LOG_DIR, "security_audit.jsonl"))
file_handler.setFormatter(logging.Formatter('%(message)s'))
audit_logger.addHandler(file_handler)

class SecurityAudit:
    """Security audit logger wrapper"""
    
    @staticmethod
    def log_event(
        event_type: str, 
        status: str, 
        details: Dict[str, Any], 
        user_id: Optional[int] = None,
        severity: str = "INFO"
    ):
        """
        Log a security event.
        
        Args:
            event_type: Type of event (e.g., "PROMPT_INJECTION", "DATA_LEAK", "ACCESS_DENIED")
            status: Outcome (BLOCKED, ALLOWED, DETECTED)
            details: Contextual details (redacted input, scores, etc.)
            user_id: ID of the user triggering the event
            severity: INFO, WARNING, CRITICAL
        """
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event_type,
            "status": status,
            "severity": severity,
            "user_id": user_id,
            "details": details
        }
        
        # Log structured JSON
        audit_logger.info(json.dumps(event))
        
        # Also log to main application stderr if critical
        if severity == "CRITICAL":
            # Assuming main app logger handles stderr/stdout
            # Implementation detail: could import main logger here if needed
            pass

    @staticmethod
    def log_injection_attempt(query: str, confidence: float, user_id: Optional[int] = None):
        """Helper to log prompt injection attempts"""
        SecurityAudit.log_event(
            event_type="PROMPT_INJECTION",
            status="BLOCKED",
            severity="WARNING",
            user_id=user_id,
            details={
                "confidence_score": confidence,
                "query_snippet": query[:100] + "..." if len(query) > 100 else query
            }
        )

    @staticmethod
    def log_leak_prevention(leak_type: str, count: int, user_id: Optional[int] = None):
        """Helper to log data leak prevention events"""
        SecurityAudit.log_event(
            event_type="DATA_LEAK_PREVENTION",
            status="REDACTED",
            severity="INFO",
            user_id=user_id,
            details={
                "leak_type": leak_type,
                "redacted_count": count
            }
        )
