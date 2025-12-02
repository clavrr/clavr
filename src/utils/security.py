"""
Security utilities for token generation and verification
"""
import secrets
import hashlib
import hmac
from typing import Tuple


def generate_session_token() -> Tuple[str, str]:
    """
    Generate a session token and its hash
    
    Returns:
        Tuple of (raw_token, hashed_token)
    """
    raw_token = secrets.token_urlsafe(32)
    hashed_token = hash_token(raw_token)
    return raw_token, hashed_token


def hash_token(token: str) -> str:
    """
    Hash a token using SHA256
    
    Args:
        token: The token to hash
        
    Returns:
        Hex-encoded hash
    """
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def verify_token(raw_token: str, hashed_token: str) -> bool:
    """
    Verify a token against its hash using constant-time comparison
    
    Args:
        raw_token: The raw token to verify
        hashed_token: The expected hash
        
    Returns:
        True if token matches hash
    """
    return hmac.compare_digest(hash_token(raw_token), hashed_token)


def generate_api_key(prefix: str = "sk") -> Tuple[str, str]:
    """
    Generate an API key with a prefix
    
    Args:
        prefix: Key prefix (default "sk")
        
    Returns:
        Tuple of (raw_key, hashed_key)
    """
    raw_key = f"{prefix}_{secrets.token_urlsafe(24)}"
    hashed_key = hash_token(raw_key)
    return raw_key, hashed_key


def constant_time_compare(s1: str, s2: str) -> bool:
    """
    Compare two strings in constant time
    
    Args:
        s1: First string
        s2: Second string
        
    Returns:
        True if strings are equal
    """
    return hmac.compare_digest(s1.encode('utf-8'), s2.encode('utf-8'))

