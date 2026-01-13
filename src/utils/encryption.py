"""
Token Encryption Module

Provides secure encryption/decryption for Gmail tokens using Fernet symmetric encryption.
Tokens are encrypted before storage in the database and decrypted when retrieved.

Security:
    - Uses Fernet (symmetric authenticated encryption)
    - Keys can be provided via ENCRYPTION_KEY environment variable
    - Automatically generates key if ENCRYPTION_KEY not set (with warning)
    - Each encryption uses a random nonce (same plaintext = different ciphertext)
"""
import os
from typing import Optional
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

from .logger import setup_logger

logger = setup_logger(__name__)

# Singleton instance
_encryption_instance: Optional['TokenEncryption'] = None


class TokenEncryption:
    """
    Token encryption/decryption using Fernet symmetric encryption.
    
    Uses Fernet which provides:
    - Authenticated encryption (prevents tampering)
    - Random nonce per encryption (same plaintext = different ciphertext)
    - Base64 encoding for safe storage
    
    Example:
        encryption = TokenEncryption()
        encrypted = encryption.encrypt("my_secret_token")
        decrypted = encryption.decrypt(encrypted)
    """
    
    def __init__(self, key: Optional[str] = None):
        """
        Initialize encryption with a key.
        
        Args:
            key: Fernet key (base64-encoded string). If None, uses ENCRYPTION_KEY
                 from environment or generates a new key (with warning).
        """
        if key is None:
            key = os.getenv('ENCRYPTION_KEY')
        
        if key is None:
            # Generate a new key (not recommended for production)
            key = generate_key()
            logger.warning(
                "ENCRYPTION_KEY not set. Generated a new key. "
                "This key will be different on each restart. "
                "Set ENCRYPTION_KEY environment variable for production use."
            )
        
        # Process the key to get key_bytes (must be exactly 32 bytes)
        key_bytes = None
        
        if isinstance(key, str):
            key = key.strip()
            
            if not key:
                # Empty string - generate new key
                logger.warning("ENCRYPTION_KEY is empty. Generating new key.")
                key = generate_key()
            
            # Check if it's a valid Fernet key (44 chars, base64-urlsafe)
            is_valid_fernet_key = (
                len(key) == 44 and 
                all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_=' for c in key)
            )
            
            if is_valid_fernet_key:
                # Try to use it as-is (Fernet expects base64-encoded bytes, not decoded)
                try:
                    # Convert string to bytes (Fernet expects base64-encoded bytes)
                    key_bytes = key.encode('utf-8')
                    # Verify it's 44 bytes (base64-encoded Fernet key)
                    if len(key_bytes) != 44:
                        raise ValueError(f"Key is {len(key_bytes)} bytes, expected 44")
                    # Test if it's a valid Fernet key by creating a Fernet instance
                    Fernet(key_bytes)
                    # If we get here, it's valid - use it
                except (ValueError, TypeError, Exception) as e:
                    logger.warning(
                        f"ENCRYPTION_KEY looks valid but failed validation: {e}. "
                        "Generating new key. Existing encrypted tokens may not be decryptable. "
                        "Set a valid ENCRYPTION_KEY (44-char base64 string) to fix this."
                    )
                    # Will generate new key below
                    key_bytes = None
            else:
                # Not a valid Fernet key format - try to derive one from it for backward compatibility
                logger.info(
                    f"ENCRYPTION_KEY is not a standard Fernet key format (got {len(key)} chars, expected 44). "
                    "Deriving Fernet key from provided value using PBKDF2."
                )
                try:
                    salt = b'notely_agent_salt'  # Fixed salt for consistency
                    kdf = PBKDF2HMAC(
                        algorithm=hashes.SHA256(),
                        length=32,
                        salt=salt,
                        iterations=100000,
                        backend=default_backend()
                    )
                    derived_raw = kdf.derive(key.encode('utf-8'))
                    # Verify the derived key is 32 bytes
                    if len(derived_raw) != 32:
                        raise ValueError(f"Derived key is {len(derived_raw)} bytes, expected 32")
                    # Fernet expects base64-encoded key, so encode the raw bytes
                    key_bytes = base64.urlsafe_b64encode(derived_raw)
                    # Verify it's 44 bytes (base64-encoded)
                    if len(key_bytes) != 44:
                        raise ValueError(f"Encoded key is {len(key_bytes)} bytes, expected 44")
                    # Test if it's a valid Fernet key
                    Fernet(key_bytes)
                except Exception as e:
                    logger.error(
                        f"Failed to derive encryption key from ENCRYPTION_KEY: {e}. "
                        "Generating new key. Existing encrypted tokens may not be decryptable."
                    )
                    # Will generate new key below
                    key_bytes = None
        
        # If we don't have a valid key_bytes yet, generate a new one
        if key_bytes is None:
            logger.warning("Generating new encryption key.")
            try:
                # Generate key directly as bytes (returns 44-byte base64-encoded key)
                key_bytes = Fernet.generate_key()
                # Verify it's 44 bytes (base64-encoded Fernet key)
                if len(key_bytes) != 44:
                    raise ValueError(f"Generated key is {len(key_bytes)} bytes, expected 44")
            except Exception as e:
                logger.error(f"Failed to generate valid encryption key: {e}")
                # Try one more time with direct generation
                try:
                    key_bytes = Fernet.generate_key()
                except Exception as e2:
                    raise ValueError(f"Cannot initialize encryption: {e2}")
        
        # Final validation
        if not isinstance(key_bytes, bytes):
            raise ValueError("Key must be bytes")
        
        # Fernet expects base64-encoded key (44 bytes)
        if len(key_bytes) != 44:
            logger.error(f"Encryption key is {len(key_bytes)} bytes, but Fernet requires 44 base64-encoded bytes.")
            raise ValueError(f"Invalid key length: {len(key_bytes)} bytes, expected 44")
        
        # Initialize Fernet - this will validate the key format
        try:
            self.fernet = Fernet(key_bytes)
        except Exception as e:
            logger.error(f"Failed to initialize Fernet encryption: {e}")
            # Last resort: generate a completely fresh key
            logger.warning("Attempting to generate a fresh encryption key as last resort...")
            try:
                fresh_key = Fernet.generate_key()
                self.fernet = Fernet(fresh_key)
                logger.warning("Using newly generated encryption key. Existing encrypted tokens will not be decryptable.")
            except Exception as e2:
                logger.error(f"Failed to generate fresh encryption key: {e2}")
                raise ValueError(f"Cannot initialize encryption: {e}")
    
    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a token.
        
        Args:
            plaintext: Token to encrypt
            
        Returns:
            Base64-encoded encrypted token
            
        Raises:
            TypeError: If plaintext is None
        """
        if plaintext is None:
            raise TypeError("Cannot encrypt None value")
        
        try:
            encrypted_bytes = self.fernet.encrypt(plaintext.encode('utf-8'))
            return encrypted_bytes.decode('utf-8')
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise
    
    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt a token.
        
        Attempts to decrypt the token. If decryption fails, checks if the token
        might be plaintext (unencrypted) from an older version of the system.
        
        Args:
            ciphertext: Base64-encoded encrypted token, or potentially plaintext token
            
        Returns:
            Decrypted token (or plaintext token if it wasn't encrypted)
            
        Raises:
            Exception: If decryption fails and token doesn't appear to be plaintext
        """
        if ciphertext is None:
            raise TypeError("Cannot decrypt None value")
        
        if not ciphertext or not isinstance(ciphertext, str):
            raise ValueError(f"Cannot decrypt invalid ciphertext: {type(ciphertext)}")
        
        # Try to decrypt
        try:
            decrypted_bytes = self.fernet.decrypt(ciphertext.encode('utf-8'))
            return decrypted_bytes.decode('utf-8')
        except Exception as e:
            # Decryption failed - check if it might be plaintext
            # OAuth tokens typically have specific patterns:
            # - Access tokens: start with "ya29." or similar
            # - Refresh tokens: start with "1//" or are long base64-like strings
            error_type = type(e).__name__
            error_msg = str(e) if str(e) else "Unknown error"
            
            # Check if it looks like a plaintext OAuth token
            is_likely_plaintext = (
                ciphertext.startswith('ya29.') or  # Google access token pattern
                ciphertext.startswith('1//') or    # Google refresh token pattern
                (len(ciphertext) > 50 and not '=' in ciphertext[-10:])  # Long token without base64 padding
            )
            
            if is_likely_plaintext:
                # Token appears to be plaintext (from before encryption was added)
                logger.debug(
                    f"Token appears to be plaintext (not encrypted). "
                    f"Using as-is. This may indicate an old token format."
                )
                return ciphertext
            
            # Not plaintext and decryption failed - this is a real error
            # Log at warning level (not error) since stale tokens are expected
            logger.warning(
                f"Decryption failed: {error_type} - {error_msg} "
                f"(ciphertext length: {len(ciphertext) if ciphertext else 0}). "
                f"Token may be encrypted with a different key or corrupted."
            )
            raise


def generate_key() -> str:
    """
    Generate a new Fernet encryption key.
    
    Returns:
        Base64-encoded Fernet key (44 characters)
    """
    key = Fernet.generate_key()
    return key.decode('utf-8')


def get_encryption() -> TokenEncryption:
    """
    Get the singleton encryption instance.
    
    Returns:
        Shared TokenEncryption instance
    """
    global _encryption_instance
    
    if _encryption_instance is None:
        _encryption_instance = TokenEncryption()
    
    return _encryption_instance


def encrypt_token(token: str) -> str:
    """
    Helper function to encrypt a token using the singleton instance.
    
    Args:
        token: Token to encrypt
        
    Returns:
        Encrypted token (base64-encoded)
    """
    encryption = get_encryption()
    return encryption.encrypt(token)


def decrypt_token(encrypted_token: str) -> str:
    """
    Helper function to decrypt a token using the singleton instance.
    
    Args:
        encrypted_token: Encrypted token (base64-encoded)
        
    Returns:
        Decrypted token
    """
    encryption = get_encryption()
    return encryption.decrypt(encrypted_token)

