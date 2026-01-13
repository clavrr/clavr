"""
Memory System Facade

This file is maintained for backward compatibility.
It re-exports components from the new modular structure.
"""
from typing import Optional, Any
from sqlalchemy.orm import Session

from .models.persistence import (
    QueryPattern,
    ExecutionMemory,
    MemoryPattern,
    UserPreference,
    UnifiedContext
)
from .core.base_memory import SimplifiedMemorySystem
from .core.hybrid_memory import HybridMemorySystem
from .components.integrator import MemoryIntegrator

# Factory functions
def create_memory_system(db: Optional[Session] = None, batch_size: int = 10) -> SimplifiedMemorySystem:
    """Factory function to create memory system"""
    return SimplifiedMemorySystem(db, batch_size)

def create_memory_integrator(memory_system: SimplifiedMemorySystem) -> MemoryIntegrator:
    """Factory function to create memory integrator"""
    return MemoryIntegrator(memory_system)

def create_hybrid_memory(
    db: Optional[Session] = None,
    batch_size: int = 10,
    vector_collection: str = "emails",
    enable_semantic: bool = True,
    rag_engine: Optional[Any] = None
) -> HybridMemorySystem:
    """Factory function to create hybrid memory system"""
    return HybridMemorySystem(
        db=db,
        batch_size=batch_size,
        vector_collection=vector_collection,
        enable_semantic=enable_semantic,
        rag_engine=rag_engine
    )
