"""
Memory Module - Agent learning and pattern memory

Provides:
- SimplifiedMemorySystem: Basic memory system for query pattern learning
- MemoryIntegrator: Integrates memory with orchestrator execution
- create_memory_system: Factory function for creating memory systems
"""

from .memory_system import (
    SimplifiedMemorySystem,
    MemoryIntegrator,
    create_memory_system,
    create_memory_integrator
)

__all__ = [
    'SimplifiedMemorySystem',
    'MemoryIntegrator',
    'create_memory_system',
    'create_memory_integrator'
]

