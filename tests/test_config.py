"""
Tests for configuration
"""
import pytest
import os
from pathlib import Path

from src.utils.config import load_config, _replace_env_vars


class TestConfig:
    """Test configuration loading and management"""
    
    def test_replace_env_vars(self, monkeypatch):
        """Test environment variable replacement"""
        monkeypatch.setenv("TEST_VAR", "test_value")
        
        obj = {
            "key1": "${TEST_VAR}",
            "key2": "normal_value",
            "nested": {
                "key3": "${TEST_VAR}"
            }
        }
        
        result = _replace_env_vars(obj)
        assert result["key1"] == "test_value"
        assert result["key2"] == "normal_value"
        assert result["nested"]["key3"] == "test_value"
    
    def test_replace_env_vars_list(self, monkeypatch):
        """Test environment variable replacement in lists"""
        monkeypatch.setenv("TEST_VAR", "test_value")
        
        obj = ["${TEST_VAR}", "normal", {"key": "${TEST_VAR}"}]
        result = _replace_env_vars(obj)
        
        assert result[0] == "test_value"
        assert result[1] == "normal"
        assert result[2]["key"] == "test_value"

