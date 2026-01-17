#!/usr/bin/env python3
"""
Live monitoring script for email indexing
Shows real-time progress updates
"""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from src.database import get_db_context
from src.database.models import User
from celery.result import AsyncResult
from src.workers.celery_app import celery_app

def monitor_indexing(user_id=3, task_id=None, interval=5):
    """Monitor indexing progress in real-time"""
    print("\n" + "="*60)
    print("LIVE EMAIL INDEXING MONITOR")
    print("="*60)
    print(f"Monitoring user ID: {user_id}")
    if task_id:
        print(f"Task ID: {task_id}")
    print(f"Update interval: {interval} seconds")
    print("Press Ctrl+C to stop\n")
    
    last_count = 0
    start_time = time.time()
    
    try:
        while True:
            # Check task status
            if task_id:
                result = AsyncResult(task_id, app=celery_app)
                task_status = result.state
            else:
                task_status = "unknown"
            
            # Check user status
            with get_db_context() as db:
                user = db.query(User).filter(User.id == user_id).first()
                if user:
                    current_count = user.total_emails_indexed or 0
                    progress = user.indexing_progress_percent or 0.0
                    status = user.indexing_status
                    
                    # Calculate rate
                    elapsed = time.time() - start_time
                    if elapsed > 0 and current_count > last_count:
                        rate = (current_count - last_count) / (interval / 60)  # emails per minute
                    else:
                        rate = 0
                    
                    # Display status
                    print(f"\r[{time.strftime('%H:%M:%S')}] Status: {status:12} | "
                          f"Progress: {progress:5.1f}% | "
                          f"Indexed: {current_count:5} | "
                          f"Rate: {rate:5.1f} emails/min | "
                          f"Task: {task_status:10}", end='', flush=True)
                    
                    # Show new emails indexed
                    if current_count > last_count:
                        new_emails = current_count - last_count
                        print(f"\n   ✅ +{new_emails} emails indexed in last {interval}s")
                    
                    last_count = current_count
                    
                    # Check if completed
                    if status == 'completed':
                        print(f"\n\n✅ INDEXING COMPLETED!")
                        print(f"   Total emails indexed: {current_count}")
                        break
                    elif status == 'failed':
                        print(f"\n\n❌ INDEXING FAILED!")
                        break
            
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print("\n\n⏹️  Monitoring stopped by user")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Monitor email indexing progress')
    parser.add_argument('--user-id', type=int, default=3, help='User ID to monitor')
    parser.add_argument('--task-id', type=str, help='Task ID to monitor')
    parser.add_argument('--interval', type=int, default=5, help='Update interval in seconds')
    
    args = parser.parse_args()
    monitor_indexing(user_id=args.user_id, task_id=args.task_id, interval=args.interval)



