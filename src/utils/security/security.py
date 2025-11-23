"""
Security Utilities - Token Hashing and Validation
"""
import hashlib
import secrets
from typing import Tuple

from ..logger import setup_logger

logger = setup_logger(__name__)


def generate_session_token() -> Tuple[str, str]:
    """
    Generate a secure session token and its hash
    
    Returns:
        Tuple of (raw_token, hashed_token)
        - raw_token: The token to send to the client (never store this)
        - hashed_token: The hashed token to store in the database
    
    Example:
        >>> raw_token, hashed_token = generate_session_token()
        >>> # Send raw_token to client, store hashed_token in database
    """
    # Generate cryptographically secure random token (32 bytes = 256 bits)
    raw_token = secrets.token_urlsafe(32)
    
    # Hash the token for storage (SHA-256)
    hashed_token = hash_token(raw_token)
    
    logger.debug("Generated new session token")
    return raw_token, hashed_token


def hash_token(token: str) -> str:
    """
    Hash a token using SHA-256
    
    Args:
        token: Raw token string to hash
        
    Returns:
        Hexadecimal hash string (64 characters)
        
    Example:
        >>> hashed = hash_token("my_secret_token")
        >>> len(hashed)
        64
    """
    # Use SHA-256 for hashing (fast, secure for this use case)
    # Note: We don't need password hashing (bcrypt/argon2) since tokens are random
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def verify_token(raw_token: str, hashed_token: str) -> bool:
    """
    Verify a raw token against its hash
    
    Args:
        raw_token: The raw token from the client
        hashed_token: The stored hash from the database
        
    Returns:
        True if token matches the hash, False otherwise
        
    Example:
        >>> raw, hashed = generate_session_token()
        >>> verify_token(raw, hashed)
        True
        >>> verify_token("wrong_token", hashed)
        False
    """
    # Hash the raw token and compare with stored hash
    # Use secrets.compare_digest to prevent timing attacks
    computed_hash = hash_token(raw_token)
    return secrets.compare_digest(computed_hash, hashed_token)


def generate_api_key(prefix: str = "sk") -> Tuple[str, str]:
    """
    Generate an API key with prefix and hash
    
    Args:
        prefix: Prefix for the API key (default: "sk")
        
    Returns:
        Tuple of (raw_api_key, hashed_api_key)
        
    Example:
        >>> raw_key, hashed_key = generate_api_key("sk")
        >>> raw_key.startswith("sk_")
        True
    """
    # Generate random key
    random_part = secrets.token_urlsafe(32)
    raw_api_key = f"{prefix}_{random_part}"
    
    # Hash for storage
    hashed_api_key = hash_token(raw_api_key)
    
    logger.debug(f"Generated new API key with prefix: {prefix}")
    return raw_api_key, hashed_api_key


def constant_time_compare(a: str, b: str) -> bool:
    """
    Compare two strings in constant time to prevent timing attacks
    
    Args:
        a: First string
        b: Second string
        
    Returns:
        True if strings match, False otherwise
    """
    return secrets.compare_digest(a, b)
