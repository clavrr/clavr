#!/usr/bin/env python3
"""
Monitor email indexing progress in real-time

Usage:
    python monitor_indexing_progress.py --user-id 2
    python monitor_indexing_progress.py --user-email user@example.com
"""
import argparse
import time
import sys
from datetime import datetime
from src.database import get_db_context
from src.database.models import User

def format_timestamp(dt):
    """Format datetime for display"""
    if not dt:
        return "N/A"
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def monitor_progress(user_id: int, interval: float = 2.0):
    """Monitor indexing progress with real-time updates"""
    print(f"\n{'='*60}")
    print(f"📊 Monitoring Email Indexing Progress")
    print(f"{'='*60}")
    print(f"User ID: {user_id}")
    print(f"Update interval: {interval}s")
    print(f"{'='*60}\n")
    
    last_status = None
    last_progress = None
    
    try:
        while True:
            with get_db_context() as db:
                user = db.query(User).filter(User.id == user_id).first()
                
                if not user:
                    print(f"❌ User {user_id} not found!")
                    break
                
                status = user.indexing_status or 'not_started'
                progress = user.indexing_progress_percent or 0.0
                total_indexed = user.total_emails_indexed or 0
                
                # Only print if status or progress changed
                if status != last_status or progress != last_progress:
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    
                    # Status indicator
                    if status == 'completed':
                        status_icon = "✅"
                    elif status == 'failed':
                        status_icon = "❌"
                    elif status == 'in_progress':
                        status_icon = "⏳"
                    else:
                        status_icon = "⏸️"
                    
                    # Progress bar
                    bar_length = 40
                    filled = int(bar_length * progress / 100)
                    bar = "█" * filled + "░" * (bar_length - filled)
                    
                    print(f"\r[{timestamp}] {status_icon} {status.upper():12} | {bar} | {progress:5.1f}% | Indexed: {total_indexed:4d}", end="", flush=True)
                    
                    # Print details on new line when status changes
                    if status != last_status:
                        print()  # New line
                        if user.indexing_started_at:
                            print(f"   Started: {format_timestamp(user.indexing_started_at)}")
                        if user.indexing_completed_at:
                            print(f"   Completed: {format_timestamp(user.indexing_completed_at)}")
                    
                    last_status = status
                    last_progress = progress
                
                # Check if completed or failed
                if status in ['completed', 'failed']:
                    print("\n")
                    if status == 'completed':
                        print(f"✅ Indexing completed! Total emails indexed: {total_indexed}")
                    else:
                        print(f"❌ Indexing failed!")
                    break
            
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print("\n\n⏹️  Monitoring stopped by user")
    except Exception as e:
        print(f"\n\n❌ Error monitoring progress: {e}")
        import traceback
        traceback.print_exc()

def main():
    parser = argparse.ArgumentParser(description="Monitor email indexing progress")
    parser.add_argument("--user-id", type=int, help="User ID to monitor")
    parser.add_argument("--user-email", type=str, help="User email to monitor")
    parser.add_argument("--interval", type=float, default=2.0, help="Update interval in seconds (default: 2.0)")
    
    args = parser.parse_args()
    
    user_id = args.user_id
    
    # If email provided, look up user ID
    if not user_id and args.user_email:
        with get_db_context() as db:
            user = db.query(User).filter(User.email == args.user_email).first()
            if not user:
                print(f"❌ User with email {args.user_email} not found!")
                sys.exit(1)
            user_id = user.id
            print(f"Found user: {user.email} (ID: {user_id})")
    
    if not user_id:
        parser.print_help()
        sys.exit(1)
    
    monitor_progress(user_id, args.interval)

if __name__ == "__main__":
    main()



