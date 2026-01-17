"""
Unit tests for token refresh functionality

Tests the critical bug fix: credentials.expiry must be set when creating credentials
"""
import pytest
import sys
import os
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch
from google.oauth2.credentials import Credentials

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.auth.token_refresh import get_valid_credentials
from src.database.models import Session as DBSession


class TestCredentialExpiry:
    """Test that credentials.expiry is properly set"""
    
    def test_expiry_is_set_from_database(self):
        """Test that credentials.expiry is set from database session"""
        print("\n[TEST 1] Testing expiry is set from database...")
        
        # Create mock database session
        mock_db_session = Mock(spec=DBSession)
        mock_db_session.id = 1
        mock_db_session.user_id = 2
        mock_db_session.gmail_access_token = "encrypted_access_token"
        mock_db_session.gmail_refresh_token = "encrypted_refresh_token"
        mock_db_session.token_expiry = datetime.utcnow() + timedelta(hours=1)
        
        # Create mock db
        mock_db = Mock()
        
        # Mock encryption functions
        with patch('src.auth.token_refresh.decrypt_token') as mock_decrypt:
            mock_decrypt.side_effect = lambda x: f"decrypted_{x}"
            
            # Mock environment variables
            with patch.dict(os.environ, {
                'GOOGLE_CLIENT_ID': 'test_client_id',
                'GOOGLE_CLIENT_SECRET': 'test_client_secret'
            }):
                # Call the function
                credentials = get_valid_credentials(mock_db, mock_db_session, auto_refresh=False)
                
                # CRITICAL TEST: Check that expiry is set
                assert credentials is not None, "Credentials should not be None"
                assert credentials.expiry is not None, "❌ BUG: credentials.expiry is None!"
                assert credentials.expiry == mock_db_session.token_expiry, "❌ BUG: expiry doesn't match database!"
                
                print(f"✅ credentials.expiry is set correctly: {credentials.expiry}")
                print(f"✅ Database token_expiry: {mock_db_session.token_expiry}")
                print(f"✅ Match: {credentials.expiry == mock_db_session.token_expiry}")
    
    def test_expiry_none_when_not_in_database(self):
        """Test that credentials.expiry is None when not in database"""
        print("\n[TEST 2] Testing expiry when not in database...")
        
        # Create mock database session WITHOUT expiry
        mock_db_session = Mock(spec=DBSession)
        mock_db_session.id = 1
        mock_db_session.user_id = 2
        mock_db_session.gmail_access_token = "encrypted_access_token"
        mock_db_session.gmail_refresh_token = "encrypted_refresh_token"
        mock_db_session.token_expiry = None  # No expiry in database
        
        # Create mock db
        mock_db = Mock()
        
        # Mock encryption functions
        with patch('src.auth.token_refresh.decrypt_token') as mock_decrypt:
            mock_decrypt.side_effect = lambda x: f"decrypted_{x}"
            
            # Mock environment variables
            with patch.dict(os.environ, {
                'GOOGLE_CLIENT_ID': 'test_client_id',
                'GOOGLE_CLIENT_SECRET': 'test_client_secret'
            }):
                # Call the function
                credentials = get_valid_credentials(mock_db, mock_db_session, auto_refresh=False)
                
                # Check that expiry is None (expected behavior)
                assert credentials is not None, "Credentials should not be None"
                assert credentials.expiry is None, "Expiry should be None when not in database"
                
                print(f"✅ credentials.expiry is None (as expected)")
    
    def test_credentials_structure(self):
        """Test that credentials object has all required fields"""
        print("\n[TEST 3] Testing credentials structure...")
        
        # Create mock database session
        future_expiry = datetime.utcnow() + timedelta(hours=1)
        mock_db_session = Mock(spec=DBSession)
        mock_db_session.id = 1
        mock_db_session.user_id = 2
        mock_db_session.gmail_access_token = "encrypted_access_token"
        mock_db_session.gmail_refresh_token = "encrypted_refresh_token"
        mock_db_session.token_expiry = future_expiry
        
        # Create mock db
        mock_db = Mock()
        
        # Mock encryption functions
        with patch('src.auth.token_refresh.decrypt_token') as mock_decrypt:
            mock_decrypt.side_effect = lambda x: f"decrypted_{x}"
            
            # Mock environment variables
            with patch.dict(os.environ, {
                'GOOGLE_CLIENT_ID': 'test_client_id',
                'GOOGLE_CLIENT_SECRET': 'test_client_secret'
            }):
                # Call the function
                credentials = get_valid_credentials(mock_db, mock_db_session, auto_refresh=False)
                
                # Check all required fields
                assert credentials.token == "decrypted_encrypted_access_token", "Access token mismatch"
                assert credentials.refresh_token == "decrypted_encrypted_refresh_token", "Refresh token mismatch"
                assert credentials.client_id == "test_client_id", "Client ID mismatch"
                assert credentials.client_secret == "test_client_secret", "Client secret mismatch"
                assert credentials.token_uri == "https://oauth2.googleapis.com/token", "Token URI mismatch"
                assert credentials.expiry == future_expiry, "Expiry mismatch"
                
                print(f"✅ All credential fields are correct:")
                print(f"   - token: {credentials.token}")
                print(f"   - refresh_token: {credentials.refresh_token}")
                print(f"   - client_id: {credentials.client_id}")
                print(f"   - expiry: {credentials.expiry}")
    
    def test_expired_credentials_detection(self):
        """Test that expired credentials are properly detected"""
        print("\n[TEST 4] Testing expired credentials detection...")
        
        # Create EXPIRED token
        past_expiry = datetime.utcnow() - timedelta(hours=1)
        
        # Create mock database session
        mock_db_session = Mock(spec=DBSession)
        mock_db_session.id = 1
        mock_db_session.user_id = 2
        mock_db_session.gmail_access_token = "encrypted_access_token"
        mock_db_session.gmail_refresh_token = "encrypted_refresh_token"
        mock_db_session.token_expiry = past_expiry
        
        # Create mock db
        mock_db = Mock()
        
        # Mock encryption functions
        with patch('src.auth.token_refresh.decrypt_token') as mock_decrypt:
            mock_decrypt.side_effect = lambda x: f"decrypted_{x}"
            
            # Mock environment variables
            with patch.dict(os.environ, {
                'GOOGLE_CLIENT_ID': 'test_client_id',
                'GOOGLE_CLIENT_SECRET': 'test_client_secret'
            }):
                # Call the function
                credentials = get_valid_credentials(mock_db, mock_db_session, auto_refresh=False)
                
                # Check that expiry is in the past
                assert credentials.expiry == past_expiry, "Expiry should match database"
                assert credentials.expired, "Credentials should be detected as expired"
                
                print(f"✅ Expired credentials properly detected:")
                print(f"✅ credentials.expiry: {credentials.expiry}")
                print(f"   - is expired: {credentials.expired}")
                print(f"   - current time: {datetime.utcnow()}")

    @pytest.mark.asyncio
    async def test_refresh_token_rotation(self):
        """Test that rotated refresh tokens are correctly saved to database"""
        print("\n[TEST 5] Testing refresh token rotation...")
        
        from src.auth.token_refresh import refresh_token_with_retry
        
        # Create mock database session with expired token
        past_expiry = datetime.utcnow() - timedelta(hours=1)
        mock_session = Mock(spec=DBSession)
        mock_session.id = 1
        mock_session.user_id = 2
        mock_session.gmail_access_token = "encrypted_old_access"
        mock_session.gmail_refresh_token = "encrypted_old_refresh"
        mock_session.token_expiry = past_expiry
        mock_session.granted_scopes = "scope1,scope2"
        
        # Track attribute changes
        mock_session.gmail_access_token = "encrypted_old_access"
        mock_session.gmail_refresh_token = "encrypted_old_refresh"
        
        # Create mock db
        mock_db = Mock()
        
        # Mock encryption/decryption
        with patch('src.auth.token_refresh.decrypt_token') as mock_decrypt, \
             patch('src.auth.token_refresh.encrypt_token') as mock_encrypt:
            
            mock_decrypt.side_effect = lambda x: f"decrypted_{x}"
            mock_encrypt.side_effect = lambda x: f"encrypted_{x}"
            
            # Mock Credentials.refresh to rotate token
            with patch('src.auth.token_refresh.Credentials') as mock_creds_class:
                mock_creds = MagicMock()
                mock_creds.expired = True
                mock_creds.token = "new_access_token"
                mock_creds.refresh_token = "new_refresh_token" # Rotated!
                mock_creds.expiry = datetime.utcnow() + timedelta(hours=1)
                
                mock_creds_class.return_value = mock_creds
                
                # Mock environment variables
                with patch.dict(os.environ, {
                    'GOOGLE_CLIENT_ID': 'test_client_id',
                    'GOOGLE_CLIENT_SECRET': 'test_client_secret'
                }):
                    # Call refresh_token_with_retry
                    was_refreshed, creds = await refresh_token_with_retry(mock_db, mock_session)
                    
                    assert was_refreshed is True
                    assert creds.token == "new_access_token"
                    assert creds.refresh_token == "new_refresh_token"
                    
                    # Verify that BOTH access and refresh tokens were encrypted and saved
                    assert mock_session.gmail_access_token == "encrypted_new_access_token"
                    assert mock_session.gmail_refresh_token == "encrypted_new_refresh_token"
                    
                    # Verify db committed
                    assert mock_db.commit.called
                    
                    print(f"✅ Refresh token rotation handled correctly:")
                    print(f"   - Old refresh token: decrypted_encrypted_old_refresh")
                    print(f"   - New refresh token: {creds.refresh_token}")
                    print(f"   - Stored encrypted refresh: {mock_session.gmail_refresh_token}")


def run_tests():
    """Run all tests and print results"""
    print("=" * 70)
    print("COMPREHENSIVE TOKEN REFRESH UNIT TESTS")
    print("=" * 70)
    
    test_suite = TestCredentialExpiry()
    
    try:
        # Test 1: Expiry is set from database
        test_suite.test_expiry_is_set_from_database()
        print("✅ TEST 1 PASSED: Expiry is set from database")
    except AssertionError as e:
        print(f"❌ TEST 1 FAILED: {e}")
        return False
    except Exception as e:
        print(f"❌ TEST 1 ERROR: {e}")
        return False
    
    try:
        # Test 2: Expiry is None when not in database
        test_suite.test_expiry_none_when_not_in_database()
        print("✅ TEST 2 PASSED: Expiry is None when not in database")
    except AssertionError as e:
        print(f"❌ TEST 2 FAILED: {e}")
        return False
    except Exception as e:
        print(f"❌ TEST 2 ERROR: {e}")
        return False
    
    try:
        # Test 3: Credentials structure
        test_suite.test_credentials_structure()
        print("✅ TEST 3 PASSED: Credentials structure is correct")
    except AssertionError as e:
        print(f"❌ TEST 3 FAILED: {e}")
        return False
    except Exception as e:
        print(f"❌ TEST 3 ERROR: {e}")
        return False
    
    try:
        # Test 4: Expired credentials detection
        test_suite.test_expired_credentials_detection()
        print("✅ TEST 4 PASSED: Expired credentials properly detected")
    except AssertionError as e:
        print(f"❌ TEST 4 FAILED: {e}")
        return False
    except Exception as e:
        print(f"❌ TEST 4 ERROR: {e}")
        return False
    
    print("\n" + "=" * 70)
    print("✅ ALL TESTS PASSED!")
    print("=" * 70)
    print("\nThe credential expiry fix is working correctly.")
    print("The Calendar API should now receive properly configured credentials.")
    return True


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
