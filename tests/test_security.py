"""
Tests for Security Utilities - Token Hashing
"""
import pytest
from src.utils.security import (
    generate_session_token,
    hash_token,
    verify_token,
    generate_api_key,
    constant_time_compare
)


class TestTokenHashing:
    """Test token generation and hashing"""
    
    def test_generate_session_token(self):
        """Test session token generation"""
        raw_token, hashed_token = generate_session_token()
        
        # Raw token should be URL-safe string
        assert isinstance(raw_token, str)
        assert len(raw_token) > 0
        assert '/' not in raw_token  # URL-safe
        
        # Hashed token should be 64 characters (SHA-256 hex)
        assert isinstance(hashed_token, str)
        assert len(hashed_token) == 64
        
        # Hashed token should be hex
        int(hashed_token, 16)  # Should not raise
    
    def test_hash_token(self):
        """Test token hashing"""
        token = "my_secret_token_123"
        hashed = hash_token(token)
        
        # Should be 64 characters (SHA-256)
        assert len(hashed) == 64
        
        # Same token should produce same hash
        hashed2 = hash_token(token)
        assert hashed == hashed2
        
        # Different token should produce different hash
        hashed3 = hash_token("different_token")
        assert hashed != hashed3
    
    def test_verify_token(self):
        """Test token verification"""
        raw_token, hashed_token = generate_session_token()
        
        # Correct token should verify
        assert verify_token(raw_token, hashed_token) is True
        
        # Wrong token should not verify
        assert verify_token("wrong_token", hashed_token) is False
        
        # Empty token should not verify
        assert verify_token("", hashed_token) is False
    
    def test_token_uniqueness(self):
        """Test that generated tokens are unique"""
        tokens = set()
        hashes = set()
        
        for _ in range(100):
            raw_token, hashed_token = generate_session_token()
            tokens.add(raw_token)
            hashes.add(hashed_token)
        
        # All tokens should be unique
        assert len(tokens) == 100
        assert len(hashes) == 100
    
    def test_token_security(self):
        """Test that tokens are cryptographically secure"""
        raw_token1, _ = generate_session_token()
        raw_token2, _ = generate_session_token()
        
        # Tokens should not be predictable
        assert raw_token1 != raw_token2
        
        # Tokens should have sufficient entropy (length)
        assert len(raw_token1) >= 40  # 32 bytes URL-safe = ~43 chars


class TestAPIKeyGeneration:
    """Test API key generation"""
    
    def test_generate_api_key(self):
        """Test API key generation"""
        raw_key, hashed_key = generate_api_key("sk")
        
        # Raw key should have prefix
        assert raw_key.startswith("sk_")
        
        # Hashed key should be 64 characters
        assert len(hashed_key) == 64
        
        # Verify key works
        assert verify_token(raw_key, hashed_key) is True
    
    def test_api_key_custom_prefix(self):
        """Test API key with custom prefix"""
        raw_key, hashed_key = generate_api_key("test")
        
        assert raw_key.startswith("test_")
        assert verify_token(raw_key, hashed_key) is True


class TestConstantTimeCompare:
    """Test constant-time string comparison"""
    
    def test_constant_time_compare(self):
        """Test constant-time comparison"""
        # Same strings should match
        assert constant_time_compare("hello", "hello") is True
        
        # Different strings should not match
        assert constant_time_compare("hello", "world") is False
        
        # Different lengths should not match
        assert constant_time_compare("hello", "hello123") is False
        
        # Empty strings should match
        assert constant_time_compare("", "") is True


class TestHashCollisions:
    """Test hash collision resistance"""
    
    def test_no_collisions(self):
        """Test that different tokens produce different hashes"""
        hashes = {}
        
        for i in range(1000):
            token = f"token_{i}"
            hashed = hash_token(token)
            
            # No collisions
            assert hashed not in hashes
            hashes[hashed] = token
        
        assert len(hashes) == 1000


class TestSecurityProperties:
    """Test security properties of hashing"""
    
    def test_hash_irreversibility(self):
        """Test that hashes cannot be reversed to original token"""
        raw_token, hashed_token = generate_session_token()
        
        # Should not be able to determine raw token from hash
        # (This is a conceptual test - we just verify hash is different)
        assert raw_token != hashed_token
        assert len(raw_token) != len(hashed_token)
    
    def test_timing_attack_resistance(self):
        """Test that comparison is constant-time"""
        token1 = "a" * 64
        token2 = "b" * 64
        
        # Both should return False, timing should be similar
        # (This is a conceptual test - actual timing tests require benchmarking)
        result1 = constant_time_compare(token1, token2)
        result2 = constant_time_compare(token1, token1)
        
        assert result1 is False
        assert result2 is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
