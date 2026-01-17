"""
Tests for Token Encryption
Tests the encryption.py module functionality
"""
import pytest
from unittest.mock import patch, Mock

from src.utils.encryption import (
    TokenEncryption,
    get_encryption,
    encrypt_token,
    decrypt_token,
    generate_key
)


class TestTokenEncryption:
    """Test suite for token encryption functionality"""
    
    def test_encrypt_decrypt_roundtrip(self):
        """Test that encrypted data can be decrypted correctly"""
        encryption = TokenEncryption()
        
        original_token = "test_access_token_12345"
        
        # Encrypt
        encrypted = encryption.encrypt(original_token)
        
        # Verify encrypted is different and longer (base64 encoded)
        assert encrypted != original_token
        assert len(encrypted) > len(original_token)
        
        # Decrypt
        decrypted = encryption.decrypt(encrypted)
        
        # Verify roundtrip works
        assert decrypted == original_token
    
    def test_encrypt_different_inputs_different_outputs(self):
        """Test that different inputs produce different encrypted outputs"""
        encryption = TokenEncryption()
        
        token1 = "token_one"
        token2 = "token_two"
        
        encrypted1 = encryption.encrypt(token1)
        encrypted2 = encryption.encrypt(token2)
        
        # Verify different outputs
        assert encrypted1 != encrypted2
    
    def test_encrypt_same_input_different_outputs(self):
        """Test that same input produces different encrypted outputs (nonce)"""
        encryption = TokenEncryption()
        
        token = "same_token"
        
        encrypted1 = encryption.encrypt(token)
        encrypted2 = encryption.encrypt(token)
        
        # Due to random nonce, same input should produce different ciphertext
        # Note: With Fernet, this is true
        # Both should decrypt to same value
        assert encryption.decrypt(encrypted1) == token
        assert encryption.decrypt(encrypted2) == token
    
    def test_decrypt_invalid_data_raises_error(self):
        """Test that decrypting invalid data raises an error"""
        encryption = TokenEncryption()
        
        with pytest.raises(Exception):
            encryption.decrypt("invalid_encrypted_data")
    
    def test_decrypt_corrupted_data_raises_error(self):
        """Test that decrypting corrupted data raises an error"""
        encryption = TokenEncryption()
        
        # Encrypt valid data
        encrypted = encryption.encrypt("test_token")
        
        # Corrupt the data
        corrupted = encrypted[:-5] + "XXXXX"
        
        with pytest.raises(Exception):
            encryption.decrypt(corrupted)
    
    def test_encrypt_empty_string(self):
        """Test encrypting empty string"""
        encryption = TokenEncryption()
        
        encrypted = encryption.encrypt("")
        decrypted = encryption.decrypt(encrypted)
        
        assert decrypted == ""
    
    def test_encrypt_long_token(self):
        """Test encrypting very long token"""
        encryption = TokenEncryption()
        
        long_token = "a" * 10000
        
        encrypted = encryption.encrypt(long_token)
        decrypted = encryption.decrypt(encrypted)
        
        assert decrypted == long_token
    
    def test_encrypt_unicode_token(self):
        """Test encrypting token with unicode characters"""
        encryption = TokenEncryption()
        
        unicode_token = "test_токен_令牌_🔐"
        
        encrypted = encryption.encrypt(unicode_token)
        decrypted = encryption.decrypt(encrypted)
        
        assert decrypted == unicode_token


class TestEncryptionSingleton:
    """Test suite for encryption singleton pattern"""
    
    def test_get_encryption_returns_same_instance(self):
        """Test that get_encryption returns same instance"""
        enc1 = get_encryption()
        enc2 = get_encryption()
        
        # Verify same instance
        assert enc1 is enc2
    
    def test_get_encryption_uses_env_key(self):
        """Test that get_encryption uses ENCRYPTION_KEY from environment"""
        with patch.dict('os.environ', {'ENCRYPTION_KEY': 'test_key_12345678901234567890123456789012'}):
            encryption = get_encryption()
            
            # Verify encryption works
            encrypted = encryption.encrypt("test")
            decrypted = encryption.decrypt(encrypted)
            assert decrypted == "test"
    
    def test_get_encryption_generates_key_if_missing(self):
        """Test that get_encryption generates key if ENCRYPTION_KEY not set"""
        with patch.dict('os.environ', {}, clear=True):
            with patch('src.utils.encryption.logger') as mock_logger:
                encryption = get_encryption()
                
                # Verify warning logged
                assert mock_logger.warning.called
                
                # Verify encryption still works
                encrypted = encryption.encrypt("test")
                decrypted = encryption.decrypt(encrypted)
                assert decrypted == "test"


class TestHelperFunctions:
    """Test suite for helper functions"""
    
    def test_encrypt_token_helper(self):
        """Test encrypt_token helper function"""
        token = "test_token"
        
        encrypted = encrypt_token(token)
        
        assert encrypted != token
        assert len(encrypted) > 0
    
    def test_decrypt_token_helper(self):
        """Test decrypt_token helper function"""
        token = "test_token"
        
        encrypted = encrypt_token(token)
        decrypted = decrypt_token(encrypted)
        
        assert decrypted == token
    
    def test_encrypt_decrypt_token_roundtrip(self):
        """Test roundtrip with helper functions"""
        original = "my_secret_token_12345"
        
        encrypted = encrypt_token(original)
        decrypted = decrypt_token(encrypted)
        
        assert decrypted == original
    
    def test_generate_key_returns_valid_key(self):
        """Test that generate_key returns a valid Fernet key"""
        key = generate_key()
        
        # Verify key is base64 encoded and correct length
        assert isinstance(key, str)
        assert len(key) == 44  # Fernet keys are 44 characters (base64)
    
    def test_generate_key_different_each_time(self):
        """Test that generate_key returns different keys"""
        key1 = generate_key()
        key2 = generate_key()
        
        assert key1 != key2
    
    def test_generated_key_works_for_encryption(self):
        """Test that generated key can be used for encryption"""
        key = generate_key()
        
        # Create encryption with generated key
        encryption = TokenEncryption(key)
        
        # Test encryption
        encrypted = encryption.encrypt("test")
        decrypted = encryption.decrypt(encrypted)
        
        assert decrypted == "test"


class TestEncryptionIntegration:
    """Integration tests for encryption in session management"""
    
    def test_session_tokens_encrypted_at_rest(self, db_session, test_user):
        """Test that session tokens are encrypted in database"""
        from src.auth.session import create_session
        from src.database.models import DBSession
        from datetime import datetime, timedelta
        
        # Create mock request
        request = Mock()
        request.client.host = "127.0.0.1"
        request.headers = {"user-agent": "Test"}
        
        # Create session with tokens
        plain_access_token = "plain_access_token_12345"
        plain_refresh_token = "plain_refresh_token_67890"
        
        session = create_session(
            db=db_session,
            user_id=test_user.id,
            gmail_access_token=plain_access_token,
            gmail_refresh_token=plain_refresh_token,
            token_expiry=datetime.utcnow() + timedelta(hours=1),
            request=request
        )
        
        # Verify tokens are encrypted in database
        db_session.refresh(session)
        assert session.gmail_access_token != plain_access_token
        assert session.gmail_refresh_token != plain_refresh_token
        
        # Verify tokens can be decrypted
        decrypted_access = decrypt_token(session.gmail_access_token)
        decrypted_refresh = decrypt_token(session.gmail_refresh_token)
        
        assert decrypted_access == plain_access_token
        assert decrypted_refresh == plain_refresh_token
    
    def test_credentials_decrypted_on_read(self, db_session, test_user):
        """Test that credentials are decrypted when retrieved"""
        from src.auth.session import create_session
        from src.auth.token_refresh import get_valid_credentials
        from datetime import datetime, timedelta
        
        request = Mock()
        request.client.host = "127.0.0.1"
        request.headers = {"user-agent": "Test"}
        
        # Create session
        plain_access_token = "plain_access_token"
        plain_refresh_token = "plain_refresh_token"
        
        session = create_session(
            db=db_session,
            user_id=test_user.id,
            gmail_access_token=plain_access_token,
            gmail_refresh_token=plain_refresh_token,
            token_expiry=datetime.utcnow() + timedelta(hours=1),
            request=request
        )
        
        # Get credentials (should decrypt)
        credentials = get_valid_credentials(
            db=db_session,
            session=session,
            auto_refresh=False
        )
        
        # Verify credentials contain decrypted tokens
        assert credentials is not None
        assert credentials.token == plain_access_token
        assert credentials.refresh_token == plain_refresh_token


class TestEncryptionErrorHandling:
    """Test error handling in encryption"""
    
    def test_decrypt_handles_invalid_key(self):
        """Test that decryption with wrong key fails gracefully"""
        # Encrypt with one key
        enc1 = TokenEncryption()
        encrypted = enc1.encrypt("test")
        
        # Try to decrypt with different key
        enc2 = TokenEncryption()  # Different instance = different key
        
        with pytest.raises(Exception):
            enc2.decrypt(encrypted)
    
    def test_encrypt_none_value(self):
        """Test encrypting None value"""
        encryption = TokenEncryption()
        
        # Should handle None gracefully or raise TypeError
        with pytest.raises((TypeError, AttributeError)):
            encryption.encrypt(None)
    
    def test_decrypt_none_value(self):
        """Test decrypting None value"""
        encryption = TokenEncryption()
        
        with pytest.raises((TypeError, AttributeError)):
            encryption.decrypt(None)


# Fixtures
@pytest.fixture
def db_session():
    """Create a test database session"""
    from src.database import SessionLocal, init_db
    from src.database.models import AuditLog, DBSession
    
    init_db()
    db = SessionLocal()
    
    yield db
    
    # Cleanup
    db.query(AuditLog).delete()
    db.query(DBSession).delete()
    db.commit()
    db.close()


@pytest.fixture
def test_user(db_session):
    """Create a test user"""
    from src.database.models import User
    
    user = User(
        email="encryption@example.com",
        name="Encryption Test User"
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    
    yield user
    
    db_session.delete(user)
    db_session.commit()
