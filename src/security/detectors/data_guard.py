"""
Data Guard: PII Redaction & Leakage Prevention

Responsible for scanning outputs for Sensitive Personal Information (PII)
and redacting it before it reaches the user or logs.
"""
import re
from typing import Dict, Any, Optional
from ..audit import SecurityAudit
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

class DataGuard:
    """
    Guards against data leakage (PII, Credentials).
    Uses regex patterns to identify and redact sensitive data.
    """
    
    # Common PII Patterns
    PATTERNS = {
        'EMAIL': r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+',
        'PHONE_US': r'(\+?1[-.]?)?\(?\d{3}\)?[-.]?\d{3}[-.]?\d{4}',
        'CREDIT_CARD': r'\b(?:\d[ -]*?){13,16}\b',
        'SSN': r'\b\d{3}-\d{2}-\d{4}\b',
        'API_KEY_SK': r'sk-[a-zA-Z0-9]{20,}',  # Common OpenAI/Stripe style
        'API_KEY_GEN': r'[A-Za-z0-9+/]{40,}',    # Generic high-entropy strings (heuristic)
    }
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

    def sanitize_output(self, text: str, user_id: Optional[int] = None) -> str:
        """
        Redact sensitive information from text.
        
        Args:
            text: Output text to sanitize
            user_id: User ID for logging context
            
        Returns:
            Sanitized string
        """
        if not text:
            return ""
            
        sanitized = text
        total_redacted = 0
        
        # 1. Credit Card Redaction (Critical)
        sanitized, count = re.subn(self.PATTERNS['CREDIT_CARD'], '[REDACTED_CC]', sanitized)
        total_redacted += count
        
        # 2. SSN Redaction (Critical)
        sanitized, count = re.subn(self.PATTERNS['SSN'], '[REDACTED_SSN]', sanitized)
        total_redacted += count
        
        # 3. API Key Redaction (Critical)
        sanitized, count = re.subn(self.PATTERNS['API_KEY_SK'], '[REDACTED_KEY]', sanitized)
        total_redacted += count
        
        # 4. Email/Phone (Context Dependent - often needed for agents, so we might NOT redact these for USER output)
        # However, for LOGGING, we definitely should.
        # Current policy: Allow Email/Phone in user output (functionality), redact in Logs.
        # This wrapper is for USER output, so we skip email/phone redaction here 
        # unless strictly configured to "paranoid" mode.
        # Handle both dict and Config object types
        mode = None
        if isinstance(self.config, dict):
            mode = self.config.get('mode')
        else:
            mode = getattr(self.config, 'mode', None)
        
        if mode == 'paranoid':
             sanitized, count = re.subn(self.PATTERNS['EMAIL'], '[REDACTED_EMAIL]', sanitized)
             total_redacted += count
             sanitized, count = re.subn(self.PATTERNS['PHONE_US'], '[REDACTED_PHONE]', sanitized)
             total_redacted += count

        if total_redacted > 0:
            SecurityAudit.log_leak_prevention("pii_redaction", total_redacted, user_id)
            logger.info(f"Redacted {total_redacted} sensitive items from output")
            
        return sanitized

    def scan_for_leaks(self, text: str) -> bool:
        """
        Check for massive data leaks (e.g. dumping raw DB rows).
        Returns True if a leak is suspected.
        """
        # Heuristic: If output is huge and contains many JSON-like structures or excessive specific patterns
        if len(text) > 5000:
            # Check for high density of email addresses (e.g. contact dump)
            emails = re.findall(self.PATTERNS['EMAIL'], text)
            if len(emails) > 10:
                # BLOCK massive data dumps
                logger.error(f"SECURITY BLOCK: Possible data dump detected. Found {len(emails)} emails in output.")
                SecurityAudit.log_leak_prevention("massive_data_dump", len(emails), None)
                return True
                
        return False
