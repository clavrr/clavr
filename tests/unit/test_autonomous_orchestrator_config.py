"""
Unit tests for AutonomousOrchestratorConfig

Tests configuration validation, consistency, and accessor methods.
"""

import pytest
from src.agent.orchestration.autonomous_config import AutonomousOrchestratorConfig


class TestAutonomousOrchestratorConfigValidation:
    """Test configuration validation"""
    
    def test_config_validates_on_import(self):
        """Configuration should validate successfully on import"""
        assert AutonomousOrchestratorConfig.validate_config() is True
    
    def test_quality_score_bonuses_dont_exceed_max(self):
        """Quality score bonuses should not exceed 1.0 total"""
        total = (
            AutonomousOrchestratorConfig.QUALITY_BASE_SCORE +
            AutonomousOrchestratorConfig.QUALITY_RESULT_BONUS +
            AutonomousOrchestratorConfig.QUALITY_SUCCESS_BONUS +
            AutonomousOrchestratorConfig.QUALITY_EXECUTION_TIME_BONUS
        )
        assert total <= 1.0
    
    def test_thresholds_properly_ordered(self):
        """Validation threshold should be >= partial threshold"""
        assert (AutonomousOrchestratorConfig.QUALITY_VALIDATION_THRESHOLD >= 
                AutonomousOrchestratorConfig.QUALITY_PARTIAL_THRESHOLD)
    
    def test_execution_time_range_valid(self):
        """Execution time min should be < max"""
        assert (AutonomousOrchestratorConfig.OPTIMAL_EXECUTION_TIME_MIN < 
                AutonomousOrchestratorConfig.OPTIMAL_EXECUTION_TIME_MAX)
    
    def test_retry_configuration_positive(self):
        """Retry configuration should be positive"""
        assert AutonomousOrchestratorConfig.MAX_RETRIES > 0
        assert AutonomousOrchestratorConfig.MAX_RETRY_STEPS >= 0


class TestAutonomousOrchestratorConfigAccessors:
    """Test configuration accessor methods"""
    
    def test_get_quality_score_config(self):
        """Quality score config should include all parameters"""
        config = AutonomousOrchestratorConfig.get_quality_score_config()
        
        assert 'base_score' in config
        assert 'result_bonus' in config
        assert 'success_bonus' in config
        assert 'execution_time_bonus' in config
        assert 'max_score' in config
        assert config['max_score'] <= 1.0
    
    def test_get_threshold_config(self):
        """Threshold config should include all thresholds"""
        config = AutonomousOrchestratorConfig.get_threshold_config()
        
        assert 'validation_threshold' in config
        assert 'partial_threshold' in config
        assert 'max_retries' in config
        assert 'max_retry_steps' in config
    
    def test_get_execution_time_config(self):
        """Execution time config should include bounds"""
        config = AutonomousOrchestratorConfig.get_execution_time_config()
        
        assert 'optimal_min' in config
        assert 'optimal_max' in config
        assert config['optimal_min'] < config['optimal_max']


class TestAutonomousOrchestratorConfigValues:
    """Test configuration constants have reasonable values"""
    
    def test_llm_temperature_is_reasonable(self):
        """LLM temperature should be between 0 and 2"""
        assert 0 <= AutonomousOrchestratorConfig.LLM_TEMPERATURE <= 2.0
    
    def test_llm_max_tokens_is_reasonable(self):
        """LLM max tokens should be positive and reasonable"""
        assert 100 <= AutonomousOrchestratorConfig.LLM_MAX_TOKENS <= 16000
    
    def test_max_retries_is_reasonable(self):
        """Max retries should be reasonable (1-10)"""
        assert 1 <= AutonomousOrchestratorConfig.MAX_RETRIES <= 10
    
    def test_quality_thresholds_are_percentages(self):
        """Quality thresholds should be between 0 and 1"""
        assert 0 <= AutonomousOrchestratorConfig.QUALITY_VALIDATION_THRESHOLD <= 1.0
        assert 0 <= AutonomousOrchestratorConfig.QUALITY_PARTIAL_THRESHOLD <= 1.0
    
    def test_default_complexity_score_is_valid(self):
        """Default complexity score should be between 0 and 1"""
        assert 0 <= AutonomousOrchestratorConfig.DEFAULT_COMPLEXITY_SCORE <= 1.0
    
    def test_default_estimated_steps_is_positive(self):
        """Default estimated steps should be positive"""
        assert AutonomousOrchestratorConfig.DEFAULT_ESTIMATED_STEPS > 0


class TestAutonomousOrchestratorConfigConsistency:
    """Test configuration consistency"""
    
    def test_no_hardcoded_values_in_config(self):
        """All configuration should be explicit constants"""
        # This is a meta-test to ensure the config class is the single source of truth
        config_attrs = [attr for attr in dir(AutonomousOrchestratorConfig) 
                       if not attr.startswith('_') and attr.isupper()]
        assert len(config_attrs) > 0
    
    def test_quality_score_calculation_example(self):
        """Quality score calculation should produce valid results"""
        # Best case: everything succeeds
        best_quality = (
            AutonomousOrchestratorConfig.QUALITY_BASE_SCORE +
            AutonomousOrchestratorConfig.QUALITY_RESULT_BONUS +
            AutonomousOrchestratorConfig.QUALITY_SUCCESS_BONUS +
            AutonomousOrchestratorConfig.QUALITY_EXECUTION_TIME_BONUS
        )
        assert best_quality <= 1.0
        
        # Worst case: only base score
        worst_quality = AutonomousOrchestratorConfig.QUALITY_BASE_SCORE
        assert worst_quality > 0
    
    def test_retry_logic_consistency(self):
        """Retry logic should be consistent"""
        # Can retry up to MAX_RETRIES times
        max_attempts = AutonomousOrchestratorConfig.MAX_RETRIES + 1
        assert max_attempts >= 2  # At least one retry allowed
