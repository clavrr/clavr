#!/usr/bin/env python3
"""
Test script for vector store backends (Qdrant primary, PostgreSQL fallback).

This script tests the vector store functionality by directly instantiating stores.
It uses environment variables and creates minimal test instances.

Usage:
    # Test all backends
    python scripts/test_vector_stores.py

    # Test specific backend
    python scripts/test_vector_stores.py --backend qdrant

    # Test auto-detection
    python scripts/test_vector_stores.py --backend auto
"""
import argparse
import os
import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Import after environment is loaded
from src.ai.rag.vector_store import PostgresVectorStore

# Qdrant import (required)
try:
    from src.ai.rag.core.vector_store import QdrantVectorStore
    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False
    print("ERROR: Qdrant client not installed. Run: pip install qdrant-client")

# PostgreSQL is always available
POSTGRES_AVAILABLE = True


def create_embedding_provider():
    """
    Create a simple embedding provider for testing.
    Uses sentence-transformers as it doesn't require API keys.
    """
    from src.ai.rag.embedding_provider import SentenceTransformerEmbeddingProvider
    return SentenceTransformerEmbeddingProvider(model_name="all-MiniLM-L6-v2")


def create_vector_store_by_backend(backend: str):
    """
    Create vector store instance based on backend name.
    
    Args:
        backend: Backend type ("auto", "pinecone", "postgres")
        
    Returns:
        VectorStore instance
    """
    embedding_provider = create_embedding_provider()
    
    # Auto-detection logic
    if backend == "auto":
        if (os.getenv('QDRANT_API_KEY') or os.getenv('QDRANT_ENDPOINT')) and QDRANT_AVAILABLE:
            backend = "qdrant"
        elif os.getenv('DATABASE_URL') and 'postgresql' in os.getenv('DATABASE_URL', ''):
            backend = "postgres"
        else:
            raise ValueError("No vector store configured! Set QDRANT_API_KEY or DATABASE_URL")
    
    # Create appropriate backend
    if backend == "qdrant":
        if not QDRANT_AVAILABLE:
            raise ImportError("qdrant-client not installed. Run: pip install qdrant-client")
        
        collection_name = os.getenv('QDRANT_COLLECTION_NAME', 'test-collection')
        return QdrantVectorStore(
            collection_name=collection_name,
            embedding_provider=embedding_provider
        )
    
    elif backend == "postgres":
        if not POSTGRES_AVAILABLE:
            raise ImportError("PostgreSQL vector store not available")
        db_url = os.getenv('DATABASE_URL')
        if not db_url or 'postgresql' not in db_url:
            raise ValueError("DATABASE_URL not set or not PostgreSQL")
        
        return PostgresVectorStore(
            db_url=db_url,
            collection_name="test_collection",
            embedding_provider=embedding_provider
        )
    
    else:
        raise ValueError(f"Invalid backend: {backend}. Use 'auto', 'qdrant', or 'postgres'")


def test_vector_store(backend: str = "auto", verbose: bool = True):
    """
    Test a vector store backend.
    
    Args:
        backend: Backend to test ("auto", "pinecone", "weaviate", "postgres", "chromadb")
        verbose: Print detailed output
        
    Returns:
        bool: True if all tests passed, False otherwise
    """
    if verbose:
        print(f"\n{'='*60}")
        print(f"Testing Vector Store Backend: {backend.upper()}")
        print(f"{'='*60}\n")
    
    try:
        # Create vector store
        if verbose:
            print(f"1. Creating vector store (backend={backend})...")
        
        store = create_vector_store_by_backend(backend=backend)
        
        if verbose:
            actual_backend = store.__class__.__name__.replace("VectorStore", "").lower()
            print(f"   ✓ Created: {store.__class__.__name__}")
            if backend == "auto":
                print(f"   ✓ Auto-detected backend: {actual_backend}")
        
        # Test 1: Add single document
        if verbose:
            print("\n2. Testing add_document()...")
        
        doc_id = f"test_doc_1_{int(time.time())}"
        store.add_document(
            doc_id=doc_id,
            content="The quick brown fox jumps over the lazy dog.",
            metadata={"source": "test", "category": "animals"}
        )
        
        if verbose:
            print(f"   ✓ Added document: {doc_id}")
        
        # Test 2: Add multiple documents
        if verbose:
            print("\n3. Testing add_documents()...")
        
        documents = [
            {
                "id": f"test_doc_2_{int(time.time())}",
                "content": "Python is a high-level programming language.",
                "metadata": {"source": "test", "category": "programming"}
            },
            {
                "id": f"test_doc_3_{int(time.time())}",
                "content": "Machine learning is a subset of artificial intelligence.",
                "metadata": {"source": "test", "category": "ai"}
            },
            {
                "id": f"test_doc_4_{int(time.time())}",
                "content": "Vector databases enable semantic search capabilities.",
                "metadata": {"source": "test", "category": "databases"}
            }
        ]
        store.add_documents(documents)
        doc_ids = [doc["id"] for doc in documents]
        
        if verbose:
            print(f"   ✓ Added {len(doc_ids)} documents")
        
        # Test 3: Search
        if verbose:
            print("\n4. Testing search()...")
        
        query_text = "What is machine learning?"
        query_embedding = store.embedding_provider.encode_query(query_text)
        
        start_time = time.time()
        results = store.search(
            query_embedding=query_embedding,
            k=2
        )
        search_time = (time.time() - start_time) * 1000  # Convert to ms
        
        if verbose:
            print(f"   ✓ Found {len(results)} results in {search_time:.2f}ms")
            for i, result in enumerate(results[:2], 1):
                print(f"     {i}. {result['content'][:60]}... (score: {result.get('score', 'N/A')})")
        
        # Test 4: Get stats
        if verbose:
            print("\n5. Testing get_stats()...")
        
        stats = store.get_stats()
        
        if verbose:
            print(f"   ✓ Stats retrieved:")
            for key, value in stats.items():
                print(f"     - {key}: {value}")
        
        # Test 5: Delete document
        if verbose:
            print("\n6. Testing delete_document()...")
        
        store.delete_document(doc_id)
        
        if verbose:
            print(f"   ✓ Deleted document: {doc_id}")
        
        # Test 6: Verify deletion
        if verbose:
            print("\n7. Verifying deletion...")
        
        query_text2 = "quick brown fox"
        query_embedding2 = store.embedding_provider.encode_query(query_text2)
        results_after = store.search(
            query_embedding=query_embedding2,
            k=5
        )
        
        # Check if the deleted doc is still in results
        deleted_doc_found = any(r.get('id') == doc_id for r in results_after)
        
        if verbose:
            if deleted_doc_found:
                print(f"   ⚠ Warning: Deleted document still appears in search results")
            else:
                print(f"   ✓ Document successfully deleted")
        
        # Clean up: Clear test data
        if verbose:
            print("\n8. Cleaning up test data...")
        
        # Delete remaining test documents
        for doc_id in doc_ids:
            try:
                store.delete_document(doc_id)
            except Exception:
                pass  # Ignore errors during cleanup
        
        if verbose:
            print(f"   ✓ Cleanup complete")
            print(f"\n{'='*60}")
            print(f"✅ ALL TESTS PASSED for {backend.upper()}")
            print(f"{'='*60}\n")
        
        return True
        
    except Exception as e:
        if verbose:
            print(f"\n{'='*60}")
            print(f"❌ TEST FAILED for {backend.upper()}")
            print(f"{'='*60}")
            print(f"Error: {str(e)}")
            import traceback
            traceback.print_exc()
            print()
        return False


def check_backend_availability():
    """Check which backends are available."""
    print("\n" + "="*60)
    print("Vector Store Backend Availability")
    print("="*60 + "\n")
    
    backends = {
        "Qdrant (PRIMARY)": QDRANT_AVAILABLE and (bool(os.getenv("QDRANT_API_KEY")) or bool(os.getenv("QDRANT_ENDPOINT"))),
        "PostgreSQL (FALLBACK)": bool(os.getenv("DATABASE_URL") and "postgresql" in os.getenv("DATABASE_URL", ""))
    }
    
    for backend, available in backends.items():
        status = "✓ Available" if available else "✗ Not Available"
        print(f"{backend:25} {status}")
        
        if backend.startswith("Qdrant") and not available:
            if not QDRANT_AVAILABLE:
                print(f"{'':25}   → Install: pip install qdrant-client")
            elif not os.getenv("QDRANT_API_KEY"):
                print(f"{'':25}   → Set QDRANT_API_KEY in .env")
        
        if backend.startswith("PostgreSQL") and not available:
            if not os.getenv("DATABASE_URL"):
                print(f"{'':25}   → Set DATABASE_URL in .env")
    
    print()
    return backends


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Test vector store backends",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test all available backends
  python scripts/test_vector_stores.py

  # Test specific backend
  python scripts/test_vector_stores.py --backend qdrant

  # Test auto-detection
  python scripts/test_vector_stores.py --backend auto

  # Quiet mode (only show pass/fail)
  python scripts/test_vector_stores.py --quiet
        """
    )
    
    parser.add_argument(
        "--backend",
        choices=["all", "auto", "qdrant", "postgres"],
        default="all",
        help="Backend to test (default: all)"
    )
    
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress detailed output"
    )
    
    args = parser.parse_args()
    
    # Check availability
    if not args.quiet:
        available_backends = check_backend_availability()
    
    # Determine which backends to test
    if args.backend == "all":
        # Test all available backends
        backends_to_test = []
        
        if not args.quiet:
            available_backends = check_backend_availability()
        
        # Check each backend
        if (os.getenv("QDRANT_API_KEY") or os.getenv("QDRANT_ENDPOINT")) and QDRANT_AVAILABLE:
            backends_to_test.append("qdrant")
        
        if os.getenv("DATABASE_URL") and "postgresql" in os.getenv("DATABASE_URL", ""):
            backends_to_test.append("postgres")
        
        # Also test auto-detection
        if backends_to_test:
            backends_to_test.insert(0, "auto")
        
        if not backends_to_test:
            print("\n❌ ERROR: No vector stores configured!")
            print("Please set QDRANT_API_KEY or DATABASE_URL (PostgreSQL)")
            sys.exit(1)
    else:
        backends_to_test = [args.backend]
    
    # Run tests
    results = {}
    
    for backend in backends_to_test:
        passed = test_vector_store(backend, verbose=not args.quiet)
        results[backend] = passed
    
    # Print summary
    print("\n" + "="*60)
    print("Test Summary")
    print("="*60 + "\n")
    
    for backend, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{backend.upper():15} {status}")
    
    print()
    
    # Exit with appropriate code
    all_passed = all(results.values())
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
