"""
Critic Module

Self-RAG components for response validation:
- HallucinationChecker: Validates responses against graph facts
"""

from .hallucination_checker import HallucinationChecker, HallucinationResult

__all__ = [
    "HallucinationChecker",
    "HallucinationResult",
]
