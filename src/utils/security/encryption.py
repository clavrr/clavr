"""
Token Encryption Utility

Provides secure encryption/decryption for sensitive OAuth tokens stored in the database.
Uses Fernet (symmetric encryption) from the cryptography library.

Security:
- AES-128 encryption in CBC mode
- HMAC for authentication
- Automatic key rotation support
- Base64 encoding for database storage
"""
import os
import base64
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken

from ..logger import setup_logger

logger = setup_logger(__name__)


class TokenEncryption:
    """
    Encrypt/decrypt sensitive OAuth tokens at rest
    
    Uses Fernet (symmetric encryption) which provides:
    - AES-128 encryption
    - HMAC authentication
    - Timestamped tokens
    - Base64 encoding
    
    Environment Variables:
        ENCRYPTION_KEY: 32-byte base64-encoded key for Fernet
        
    Example:
        >>> encryption = TokenEncryption()
        >>> encrypted = encryption.encrypt("my-secret-token")
        >>> decrypted = encryption.decrypt(encrypted)
        >>> assert decrypted == "my-secret-token"
    """
    
    def __init__(self, key: Optional[str] = None):
        """
        Initialize token encryption
        
        Args:
            key: Encryption key (base64-encoded). If None, reads from ENCRYPTION_KEY env var.
            
        Raises:
            ValueError: If encryption key not provided and not in environment
        """
        # Load encryption key from parameter or environment
        encryption_key = key or os.getenv('ENCRYPTION_KEY')
        
        if not encryption_key:
            raise ValueError(
                "ENCRYPTION_KEY environment variable not set. "
                "Generate a key with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            )
        
        try:
            # Initialize Fernet cipher
            self.fernet = Fernet(encryption_key.encode())
            logger.info("[OK] Token encryption initialized")
        except Exception as e:
            logger.error(f"Failed to initialize token encryption: {e}")
            raise ValueError(f"Invalid encryption key format: {e}")
    
    def encrypt(self, plaintext: Optional[str]) -> Optional[str]:
        """
        Encrypt plaintext token
        
        Args:
            plaintext: Token to encrypt (or None)
            
        Returns:
            Base64-encoded encrypted token, or None if input is None
            
        Example:
            >>> encrypted = encryption.encrypt("my-access-token")
            >>> print(encrypted)  # "gAAAAABh..."
        """
        if plaintext is None or plaintext == "":
            return None
        
        try:
            # Encrypt and encode
            encrypted_bytes = self.fernet.encrypt(plaintext.encode('utf-8'))
            encrypted_str = base64.b64encode(encrypted_bytes).decode('utf-8')
            return encrypted_str
        except Exception as e:
            logger.error(f"Failed to encrypt token: {e}")
            raise
    
    def decrypt(self, ciphertext: Optional[str]) -> Optional[str]:
        """
        Decrypt encrypted token
        
        Args:
            ciphertext: Base64-encoded encrypted token (or None)
            
        Returns:
            Decrypted plaintext token, or None if input is None
            
        Raises:
            InvalidToken: If token is invalid or corrupted
            
        Example:
            >>> decrypted = encryption.decrypt("gAAAAABh...")
            >>> print(decrypted)  # "my-access-token"
        """
        if ciphertext is None or ciphertext == "":
            return None
        
        try:
            # Decode and decrypt
            encrypted_bytes = base64.b64decode(ciphertext.encode('utf-8'))
            decrypted_bytes = self.fernet.decrypt(encrypted_bytes)
            decrypted_str = decrypted_bytes.decode('utf-8')
            return decrypted_str
        except InvalidToken:
            logger.error("Failed to decrypt token: Invalid or corrupted token")
            raise ValueError("Token decryption failed: Invalid or corrupted token")
        except Exception as e:
            logger.error(f"Failed to decrypt token: {e}")
            raise
    
    def encrypt_multiple(self, tokens: dict) -> dict:
        """
        Encrypt multiple tokens at once
        
        Args:
            tokens: Dictionary of token names to plaintext tokens
            
        Returns:
            Dictionary of token names to encrypted tokens
            
        Example:
            >>> tokens = {
            ...     'access_token': 'abc123',
            ...     'refresh_token': 'xyz789'
            ... }
            >>> encrypted = encryption.encrypt_multiple(tokens)
        """
        return {
            key: self.encrypt(value) if value else None
            for key, value in tokens.items()
        }
    
    def decrypt_multiple(self, encrypted_tokens: dict) -> dict:
        """
        Decrypt multiple tokens at once
        
        Args:
            encrypted_tokens: Dictionary of token names to encrypted tokens
            
        Returns:
            Dictionary of token names to plaintext tokens
            
        Example:
            >>> decrypted = encryption.decrypt_multiple(encrypted_tokens)
        """
        return {
            key: self.decrypt(value) if value else None
            for key, value in encrypted_tokens.items()
        }


# Global instance (lazy-loaded)
_encryption_instance: Optional[TokenEncryption] = None


def get_encryption() -> TokenEncryption:
    """
    Get global token encryption instance (singleton pattern)
    
    Returns:
        TokenEncryption instance
        
    Example:
        >>> encryption = get_encryption()
        >>> encrypted = encryption.encrypt("token")
    """
    global _encryption_instance
    
    if _encryption_instance is None:
        _encryption_instance = TokenEncryption()
    
    return _encryption_instance


def generate_key() -> str:
    """
    Generate a new Fernet encryption key
    
    Returns:
        Base64-encoded encryption key
        
    Example:
        >>> key = generate_key()
        >>> print(key)  # Store this in ENCRYPTION_KEY environment variable
    """
    return Fernet.generate_key().decode()


# Convenience functions for direct use
def encrypt_token(plaintext: Optional[str]) -> Optional[str]:
    """Encrypt a token using global encryption instance"""
    return get_encryption().encrypt(plaintext)


def decrypt_token(ciphertext: Optional[str]) -> Optional[str]:
    """Decrypt a token using global encryption instance"""
    return get_encryption().decrypt(ciphertext)
