#!/usr/bin/env python3
"""
Database Index Performance Benchmark
Demonstrates query performance improvements after index implementation
"""
import sys
import os
import time
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database.database import get_db
from src.database.models import User, Session
from sqlalchemy import func

def benchmark_query(name: str, query_func, iterations: int = 100):
    """Benchmark a query function"""
    times = []
    
    for _ in range(iterations):
        start = time.perf_counter()
        query_func()
        elapsed = (time.perf_counter() - start) * 1000  # Convert to ms
        times.append(elapsed)
    
    avg_time = sum(times) / len(times)
    min_time = min(times)
    max_time = max(times)
    p95_time = sorted(times)[int(len(times) * 0.95)]
    
    print(f"\n{name}")
    print(f"  Iterations: {iterations}")
    print(f"  Average:    {avg_time:.2f}ms")
    print(f"  Min:        {min_time:.2f}ms")
    print(f"  Max:        {max_time:.2f}ms")
    print(f"  P95:        {p95_time:.2f}ms")
    
    return avg_time

def main():
    """Run performance benchmarks"""
    print("=" * 80)
    print("DATABASE INDEX PERFORMANCE BENCHMARK")
    print("=" * 80)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print()
    
    db = next(get_db())
    
    try:
        # Get total counts for context
        user_count = db.query(User).count()
        session_count = db.query(Session).count()
        
        print(f"Database Statistics:")
        print(f"  Total Users:    {user_count:,}")
        print(f"  Total Sessions: {session_count:,}")
        print()
        
        print("Running Benchmarks...")
        print("-" * 80)
        
        # Benchmark 1: Count indexed users
        def query_indexed_users():
            return db.query(User).filter(User.email_indexed == True).count()
        
        avg1 = benchmark_query(
            "Query 1: Count Users with email_indexed=True",
            query_indexed_users,
            iterations=100
        )
        
        # Benchmark 2: Get users by indexing status
        def query_users_by_status():
            return db.query(User).filter(User.indexing_status == 'completed').limit(10).all()
        
        avg2 = benchmark_query(
            "Query 2: Get Users by indexing_status",
            query_users_by_status,
            iterations=100
        )
        
        # Benchmark 3: Recent users
        def query_recent_users():
            return db.query(User).order_by(User.created_at.desc()).limit(10).all()
        
        avg3 = benchmark_query(
            "Query 3: Get Recent Users (ORDER BY created_at DESC)",
            query_recent_users,
            iterations=100
        )
        
        # Benchmark 4: Session validation (composite index)
        def query_validate_session():
            now = datetime.utcnow()
            return db.query(Session).filter(
                Session.user_id == 1,
                Session.expires_at > now
            ).first()
        
        avg4 = benchmark_query(
            "Query 4: Validate Session (user_id + expires_at)",
            query_validate_session,
            iterations=100
        )
        
        # Benchmark 5: Expired sessions cleanup
        def query_expired_sessions():
            now = datetime.utcnow()
            return db.query(Session).filter(Session.expires_at < now).limit(100).all()
        
        avg5 = benchmark_query(
            "Query 5: Find Expired Sessions",
            query_expired_sessions,
            iterations=100
        )
        
        # Benchmark 6: Recent sessions
        def query_recent_sessions():
            return db.query(Session).order_by(Session.created_at.desc()).limit(10).all()
        
        avg6 = benchmark_query(
            "Query 6: Get Recent Sessions (ORDER BY created_at DESC)",
            query_recent_sessions,
            iterations=100
        )
        
        # Summary
        print()
        print("=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"Average query time across all benchmarks: {(avg1+avg2+avg3+avg4+avg5+avg6)/6:.2f}ms")
        print()
        print("✅ All queries should show index usage")
        print("   Run EXPLAIN ANALYZE to verify index scans vs sequential scans")
        print()
        print("Expected Performance (with indexes):")
        print("  - Simple lookups:     < 5ms")
        print("  - COUNT queries:      < 10ms")
        print("  - ORDER BY queries:   < 5ms")
        print("  - Composite lookups:  < 3ms")
        print()
        
    finally:
        db.close()

if __name__ == "__main__":
    main()
