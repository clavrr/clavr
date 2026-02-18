"""
Custom SQLAlchemy types for data encryption at rest.
"""
import json
from sqlalchemy.types import TypeDecorator, Text
from src.utils.encryption import encrypt_token, decrypt_token
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

class EncryptedString(TypeDecorator):
    """
    SQLAlchemy type for transparent string encryption.
    Stores data as encrypted text in the database.
    
    Uses Fernet (authenticated symmetric encryption) via src.utils.encryption.
    Works best for fields that are not used in direct SQL equality filters,
    as encryption is non-deterministic (same input = different output).
    """
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        try:
            return encrypt_token(str(value))
        except Exception as e:
            logger.error(f"Failed to encrypt field: {e}")
            return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            # decrypt_token handles plaintext fallback automatically
            return decrypt_token(value)
        except Exception as e:
            logger.warning(f"Failed to decrypt field (might be plaintext): {e}")
            return value

class EncryptedJSON(TypeDecorator):
    """
    SQLAlchemy type for transparent JSON encryption.
    Serializes JSON to string, encrypts, and stores as text.
    """
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        try:
            json_str = json.dumps(value)
            return encrypt_token(json_str)
        except Exception as e:
            logger.error(f"Failed to encrypt JSON field: {e}")
            return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            # First try to decrypt
            json_str = decrypt_token(value)
            return json.loads(json_str)
        except Exception as e:
            # Decryption or JSON parsing failed
            # Check if it's already plaintext JSON (not encrypted)
            try:
                return json.loads(value)
            except Exception:
                logger.warning(f"Failed to process EncryptedJSON field: {e}")
                return value
