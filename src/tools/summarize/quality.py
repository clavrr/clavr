"""
Quality metrics and validation for summarization
Provides tools to measure and validate summary quality
"""
from typing import Dict, Any, Optional
import re
from ...utils.logger import setup_logger
from .constants import (
    QUALITY_MIN_COMPRESSION,
    QUALITY_MAX_COMPRESSION,
    QUALITY_MIN_COVERAGE,
    QUALITY_MIN_DENSITY
)

logger = setup_logger(__name__)


class QualityMetrics:
    """Calculate and validate summary quality metrics"""
    
    @staticmethod
    def calculate_compression_ratio(original: str, summary: str) -> float:
        """
        Calculate compression ratio (summary length / original length)
        
        Args:
            original: Original text
            summary: Summary text
            
        Returns:
            Compression ratio as float (0.0-1.0)
        """
        if not original or not summary:
            return 0.0
        
        original_len = len(original)
        summary_len = len(summary)
        
        if original_len == 0:
            return 0.0
        
        return summary_len / original_len
    
    @staticmethod
    def calculate_coverage(original: str, summary: str) -> float:
        """
        Calculate coverage (what % of original words appear in summary)
        
        Args:
            original: Original text
            summary: Summary text
            
        Returns:
            Coverage ratio as float (0.0-1.0)
        """
        if not original or not summary:
            return 0.0
        
        # Extract words (lowercase, alphanumeric only)
        original_words = set(re.findall(r'\b\w+\b', original.lower()))
        summary_words = set(re.findall(r'\b\w+\b', summary.lower()))
        
        if not original_words:
            return 0.0
        
        # Calculate intersection
        common_words = original_words & summary_words
        return len(common_words) / len(original_words)
    
    @staticmethod
    def calculate_density(summary: str) -> float:
        """
        Calculate information density (words per line)
        
        Args:
            summary: Summary text
            
        Returns:
            Density as float (words per line)
        """
        if not summary or not summary.strip():
            return 0.0
        
        lines = [line for line in summary.split('\n') if line.strip()]
        words = summary.split()
        
        if not lines:
            return 0.0
        
        return len(words) / len(lines)
    
    @staticmethod
    def calculate_all_metrics(original: str, summary: str) -> Dict[str, float]:
        """
        Calculate all quality metrics
        
        Args:
            original: Original text
            summary: Summary text
            
        Returns:
            Dictionary with all metrics
        """
        return {
            'compression_ratio': QualityMetrics.calculate_compression_ratio(original, summary),
            'coverage': QualityMetrics.calculate_coverage(original, summary),
            'density': QualityMetrics.calculate_density(summary),
            'original_length': len(original),
            'summary_length': len(summary),
            'original_words': len(original.split()),
            'summary_words': len(summary.split())
        }
    
    @staticmethod
    def validate_summary_quality(
        original: str,
        summary: str,
        min_compression: float = QUALITY_MIN_COMPRESSION,
        max_compression: float = QUALITY_MAX_COMPRESSION,
        min_coverage: float = QUALITY_MIN_COVERAGE,
        min_density: float = QUALITY_MIN_DENSITY
    ) -> tuple[bool, Optional[str]]:
        """
        Validate that summary meets quality thresholds
        
        Args:
            original: Original text
            summary: Summary text
            min_compression: Minimum compression ratio (default: QUALITY_MIN_COMPRESSION = 10%)
            max_compression: Maximum compression ratio (default: QUALITY_MAX_COMPRESSION = 80%)
            min_coverage: Minimum coverage ratio (default: QUALITY_MIN_COVERAGE = 20%)
            min_density: Minimum information density (default: QUALITY_MIN_DENSITY = 5 words/line)
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        metrics = QualityMetrics.calculate_all_metrics(original, summary)
        
        # Check compression ratio
        compression = metrics['compression_ratio']
        if compression < min_compression:
            return False, f"Summary too short (compression: {compression:.1%} < {min_compression:.1%})"
        if compression > max_compression:
            return False, f"Summary too long (compression: {compression:.1%} > {max_compression:.1%})"
        
        # Check coverage
        coverage = metrics['coverage']
        if coverage < min_coverage:
            return False, f"Summary coverage too low ({coverage:.1%} < {min_coverage:.1%})"
        
        # Check density (avoid extremely sparse summaries)
        density = metrics['density']
        if density < min_density:
            return False, f"Summary too sparse (density: {density:.1f} words/line < {min_density:.1f})"
        
        return True, None
    
    @staticmethod
    def log_metrics(metrics: Dict[str, Any], context: str = "Summary"):
        """
        Log quality metrics in a formatted way
        
        Args:
            metrics: Metrics dictionary
            context: Context label for logging
        """
        logger.info(
            f"[{context}] Compression: {metrics.get('compression_ratio', 0):.1%}, "
            f"Coverage: {metrics.get('coverage', 0):.1%}, "
            f"Density: {metrics.get('density', 0):.1f} words/line, "
            f"Length: {metrics.get('original_length', 0)} → {metrics.get('summary_length', 0)} chars"
        )
