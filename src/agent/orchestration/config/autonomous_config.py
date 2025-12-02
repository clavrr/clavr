"""
Autonomous Orchestrator Configuration

Centralized configuration for AutonomousOrchestrator with all constants,
thresholds, and tunable parameters. No hardcoded values in autonomous.py.
"""


class AutonomousOrchestratorConfig:
    """
    Configuration constants for AutonomousOrchestrator.
    
    All magic numbers and thresholds are defined here for easy tuning
    and to ensure no hardcoded values in the orchestrator implementation.
    """
    
    # LLM Configuration
    LLM_TEMPERATURE = 0.1
    LLM_MAX_TOKENS = 2000
    
    # Execution Strategy
    MAX_RETRIES = 3
    MAX_RETRY_STEPS = 2
    
    # Quality Validation Thresholds
    QUALITY_VALIDATION_THRESHOLD = 0.8
    QUALITY_PARTIAL_THRESHOLD = 0.5
    
    # Quality Score Calculation (must sum to 1.0 or less)
    QUALITY_BASE_SCORE = 0.5
    QUALITY_RESULT_BONUS = 0.2
    QUALITY_SUCCESS_BONUS = 0.2
    QUALITY_EXECUTION_TIME_BONUS = 0.1
    
    # Execution Time Thresholds (seconds)
    OPTIMAL_EXECUTION_TIME_MIN = 0.0
    OPTIMAL_EXECUTION_TIME_MAX = 5.0
    
    # Complexity Score Defaults
    DEFAULT_COMPLEXITY_SCORE = 0.5
    DEFAULT_ESTIMATED_STEPS = 3
    
    # Cache Configuration (Phase 4)
    ENABLE_REQUEST_CACHING = True
    CACHE_TIMESTAMP_FORMAT = "req_{timestamp}"
    
    # Retry Messages
    RETRY_MAX_MESSAGE = "Retry {current}/{max}"
    
    # Logging
    ENABLE_PHASE4_LOGGING = True
    ENABLE_CACHE_STATISTICS = True
    
    # Fallback Strategy
    USE_FALLBACK_AFTER_MAX_RETRIES = True
    SIMPLIFY_STRATEGY_ON_FAILURE = True
    SINGLE_STEP_FALLBACK = False
    
    @classmethod
    def validate_config(cls) -> bool:
        """
        Validate configuration consistency.
        
        Returns:
            bool: True if configuration is valid, False otherwise
        """
        # Quality score bonuses should not exceed total score
        total_bonus = (
            cls.QUALITY_RESULT_BONUS +
            cls.QUALITY_SUCCESS_BONUS +
            cls.QUALITY_EXECUTION_TIME_BONUS
        )
        max_possible_score = cls.QUALITY_BASE_SCORE + total_bonus
        
        if max_possible_score > 1.0:
            raise ValueError(
                f"Quality score configuration invalid: "
                f"base {cls.QUALITY_BASE_SCORE} + bonuses {total_bonus} = {max_possible_score} > 1.0"
            )
        
        # Thresholds should be ordered
        if cls.QUALITY_VALIDATION_THRESHOLD < cls.QUALITY_PARTIAL_THRESHOLD:
            raise ValueError(
                f"Quality thresholds invalid: "
                f"validation threshold ({cls.QUALITY_VALIDATION_THRESHOLD}) < "
                f"partial threshold ({cls.QUALITY_PARTIAL_THRESHOLD})"
            )
        
        # Execution time range should be valid
        if cls.OPTIMAL_EXECUTION_TIME_MIN > cls.OPTIMAL_EXECUTION_TIME_MAX:
            raise ValueError(
                f"Execution time range invalid: "
                f"min ({cls.OPTIMAL_EXECUTION_TIME_MIN}) > "
                f"max ({cls.OPTIMAL_EXECUTION_TIME_MAX})"
            )
        
        # Retry configuration should be positive
        if cls.MAX_RETRIES <= 0:
            raise ValueError(f"MAX_RETRIES must be positive, got {cls.MAX_RETRIES}")
        
        if cls.MAX_RETRY_STEPS < 0:
            raise ValueError(f"MAX_RETRY_STEPS must be non-negative, got {cls.MAX_RETRY_STEPS}")
        
        return True
    
    @classmethod
    def get_quality_score_config(cls) -> dict:
        """
        Get quality score calculation configuration.
        
        Returns:
            dict: Configuration for quality score calculation
        """
        return {
            'base_score': cls.QUALITY_BASE_SCORE,
            'result_bonus': cls.QUALITY_RESULT_BONUS,
            'success_bonus': cls.QUALITY_SUCCESS_BONUS,
            'execution_time_bonus': cls.QUALITY_EXECUTION_TIME_BONUS,
            'max_score': min(
                cls.QUALITY_BASE_SCORE +
                cls.QUALITY_RESULT_BONUS +
                cls.QUALITY_SUCCESS_BONUS +
                cls.QUALITY_EXECUTION_TIME_BONUS,
                1.0
            )
        }
    
    @classmethod
    def get_threshold_config(cls) -> dict:
        """
        Get quality threshold configuration.
        
        Returns:
            dict: Configuration for quality thresholds
        """
        return {
            'validation_threshold': cls.QUALITY_VALIDATION_THRESHOLD,
            'partial_threshold': cls.QUALITY_PARTIAL_THRESHOLD,
            'max_retries': cls.MAX_RETRIES,
            'max_retry_steps': cls.MAX_RETRY_STEPS,
        }
    
    @classmethod
    def get_execution_time_config(cls) -> dict:
        """
        Get execution time configuration.
        
        Returns:
            dict: Configuration for execution time bounds
        """
        return {
            'optimal_min': cls.OPTIMAL_EXECUTION_TIME_MIN,
            'optimal_max': cls.OPTIMAL_EXECUTION_TIME_MAX,
        }


# Validate configuration on import
try:
    AutonomousOrchestratorConfig.validate_config()
except ValueError as e:
    import warnings
    warnings.warn(f"AutonomousOrchestratorConfig validation failed: {e}", RuntimeWarning)
