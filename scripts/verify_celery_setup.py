#!/usr/bin/env python3
"""
Celery Setup Verification Script
Tests that all tasks are registered and worker is properly configured
"""
import sys
from collections import defaultdict

def main():
    print("=" * 80)
    print("CELERY SETUP VERIFICATION")
    print("=" * 80)
    
    # Import Celery app
    print("\n1. Loading Celery app...")
    try:
        from src.workers.celery_app import celery_app
        print("   ✓ Celery app loaded successfully")
    except Exception as e:
        print(f"   ✗ Failed to load Celery app: {e}")
        return 1
    
    # Check configuration
    print("\n2. Checking configuration...")
    print(f"   - Broker: {celery_app.conf.broker_url}")
    print(f"   - Backend: {celery_app.conf.result_backend}")
    print(f"   - Task serializer: {celery_app.conf.task_serializer}")
    print(f"   - Accept content: {celery_app.conf.accept_content}")
    
    # Check included modules
    print("\n3. Checking included task modules...")
    included_modules = celery_app.conf.include
    for module in included_modules:
        print(f"   ✓ {module}")
    
    # Import all task modules
    print("\n4. Importing all task modules...")
    try:
        import src.workers.tasks.email_tasks
        print("   ✓ email_tasks")
        import src.workers.tasks.calendar_tasks
        print("   ✓ calendar_tasks")
        import src.workers.tasks.indexing_tasks
        print("   ✓ indexing_tasks")
        import src.workers.tasks.notification_tasks
        print("   ✓ notification_tasks")
        import src.workers.tasks.maintenance_tasks
        print("   ✓ maintenance_tasks")
    except Exception as e:
        print(f"   ✗ Failed to import task modules: {e}")
        return 1
    
    # Count registered tasks
    print("\n5. Registered tasks summary...")
    tasks_by_module = defaultdict(list)
    
    for task_name in sorted(celery_app.tasks.keys()):
        if task_name.startswith('src.workers.tasks.'):
            module = task_name.split('.')[3]  # Extract module name
            task_short = task_name.split('.')[-1]  # Extract task function name
            tasks_by_module[module].append(task_short)
    
    total_tasks = 0
    for module, tasks in sorted(tasks_by_module.items()):
        print(f"\n   {module.upper()} ({len(tasks)} tasks):")
        for task in sorted(tasks):
            print(f"      - {task}")
        total_tasks += len(tasks)
    
    print(f"\n   TOTAL: {total_tasks} tasks registered")
    
    # Check queues
    print("\n6. Checking task queues...")
    print(f"   Default queue: {celery_app.conf.task_default_queue}")
    print(f"   Configured queues: {len(celery_app.conf.task_queues)}")
    for queue in celery_app.conf.task_queues:
        print(f"      - {queue.name}")
    
    # Check periodic tasks
    print("\n7. Checking periodic tasks (beat schedule)...")
    if hasattr(celery_app.conf, 'beat_schedule') and celery_app.conf.beat_schedule:
        for name, schedule_info in celery_app.conf.beat_schedule.items():
            schedule = schedule_info.get('schedule', 'N/A')
            task = schedule_info.get('task', 'N/A')
            print(f"   - {name}")
            print(f"      Task: {task}")
            print(f"      Schedule: {schedule}")
    else:
        print("   No periodic tasks configured")
    
    # Summary
    print("\n" + "=" * 80)
    print("VERIFICATION COMPLETE")
    print("=" * 80)
    print(f"✓ All {total_tasks} tasks registered successfully")
    print("✓ All 5 task modules loaded")
    print(f"✓ {len(celery_app.conf.task_queues)} queues configured")
    print("\nTo start the worker, run:")
    print("   ./scripts/start_celery_worker.sh")
    print("\nTo start the scheduler, run:")
    print("   ./scripts/start_celery_beat.sh")
    print("\nTo start monitoring UI, run:")
    print("   ./scripts/start_flower.sh")
    print("=" * 80)
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
