"""
File Encryption Utility

Provides secure encryption/decryption for files and JSON data stored on the filesystem.
Uses TokenEncryption as the underlying engine.
"""
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .encryption import get_encryption
from .logger import setup_logger

logger = setup_logger(__name__)


def encrypt_file(file_path: Union[str, Path], data: bytes) -> None:
    """
    Encrypt and save data to a file.
    
    Args:
        file_path: Path to the file
        data: Raw bytes to encrypt
    """
    try:
        encryption = get_encryption()
        # Fernet.encrypt expects bytes and returns bytes
        # TokenEncryption.encrypt expects str and returns str
        # We'll use the underlying fernet instance for raw bytes
        encrypted_data = encryption.fernet.encrypt(data)
        
        file_path = Path(file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(file_path, 'wb') as f:
            f.write(encrypted_data)
            
        logger.debug(f"Encrypted data saved to {file_path}")
    except Exception as e:
        logger.error(f"Failed to save encrypted file {file_path}: {e}")
        raise


def decrypt_file(file_path: Union[str, Path]) -> bytes:
    """
    Read and decrypt data from a file.
    
    Args:
        file_path: Path to the file
        
    Returns:
        Decrypted bytes
    """
    try:
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
            
        with open(file_path, 'rb') as f:
            encrypted_data = f.read()
            
        encryption = get_encryption()
        
        # Check if it's actually encrypted (Fernet tokens start with gAAAA)
        if not encrypted_data.startswith(b'gAAAA'):
            logger.warning(f"File {file_path} does not appear to be encrypted. Returning as-is.")
            return encrypted_data
            
        decrypted_data = encryption.fernet.decrypt(encrypted_data)
        return decrypted_data
    except Exception as e:
        logger.error(f"Failed to decrypt file {file_path}: {e}")
        raise


def save_encrypted_json(file_path: Union[str, Path], data: Any) -> None:
    """
    Encrypt and save data as JSON to a file.
    
    Args:
        file_path: Path to the file
        data: Data to be JSON-serialized and encrypted
    """
    json_data = json.dumps(data, default=str).encode('utf-8')
    encrypt_file(file_path, json_data)


def load_encrypted_json(file_path: Union[str, Path], default: Any = None) -> Any:
    """
    Read and decrypt JSON data from a file.
    
    Args:
        file_path: Path to the file
        default: Default value if file not found or decryption fails
        
    Returns:
        Decrypted and parsed JSON data
    """
    try:
        decrypted_data = decrypt_file(file_path)
        return json.loads(decrypted_data.decode('utf-8'))
    except FileNotFoundError:
        return default
    except Exception as e:
        logger.warning(f"Failed to load encrypted JSON from {file_path}: {e}")
        return default
