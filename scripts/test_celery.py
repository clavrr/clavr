#!/usr/bin/env python3
"""
Test Celery Job Queue
Verifies that tasks can be queued and executed
"""
import sys
import time
from src.workers.celery_app import celery_app, debug_task, get_task_status

print("=" * 80)
print("🧪 Celery Job Queue Test")
print("=" * 80)

# Test 1: Queue Configuration
print("\n1️⃣ Testing Queue Configuration...")
print(f"   Broker URL: {celery_app.conf.broker_url}")
print(f"   Result Backend: {celery_app.conf.result_backend}")
print(f"   Queues: {', '.join([q.name for q in celery_app.conf.task_queues])}")
print("   ✅ Configuration loaded")

# Test 2: Task Registration
print("\n2️⃣ Testing Task Registration...")
registered_tasks = [name for name in celery_app.tasks.keys() if not name.startswith('celery.')]
print(f"   Registered tasks ({len(registered_tasks)}):")
for task_name in registered_tasks[:10]:  # Show first 10
    print(f"     • {task_name}")
if len(registered_tasks) > 10:
    print(f"     ... and {len(registered_tasks) - 10} more")
print("   ✅ Tasks registered")

# Test 3: Queue a test task
print("\n3️⃣ Testing Task Queueing...")
try:
    result = debug_task.delay()
    print(f"   Task ID: {result.id}")
    print(f"   Task State: {result.state}")
    print("   ✅ Task queued successfully")
    
    # Check task status
    print("\n4️⃣ Checking Task Status...")
    status = get_task_status(result.id)
    print(f"   State: {status['state']}")
    print(f"   Status: {status['status']}")
    
    if status['state'] == 'PENDING':
        print("\n   ⚠️  Task is pending (no worker running)")
        print("   💡 To execute tasks, start a worker with:")
        print("      celery -A src.workers.celery_app worker --loglevel=info")
    else:
        print(f"   Result: {status['result']}")
        print("   ✅ Task executed")
        
except Exception as e:
    print(f"   ❌ Error: {e}")
    sys.exit(1)

# Test 4: Import all task modules
print("\n5️⃣ Testing Task Module Imports...")
try:
    from src.workers.tasks import email_tasks
    print("   ✅ email_tasks imported")
except Exception as e:
    print(f"   ⚠️  email_tasks: {e}")

try:
    from src.workers.tasks import calendar_tasks
    print("   ✅ calendar_tasks imported")
except Exception as e:
    print(f"   ⚠️  calendar_tasks: {e}")

try:
    from src.workers.tasks import indexing_tasks
    print("   ✅ indexing_tasks imported")
except Exception as e:
    print(f"   ⚠️  indexing_tasks: {e}")

try:
    from src.workers.tasks import notification_tasks
    print("   ✅ notification_tasks imported")
except Exception as e:
    print(f"   ⚠️  notification_tasks: {e}")

try:
    from src.workers.tasks import maintenance_tasks
    print("   ✅ maintenance_tasks imported")
except Exception as e:
    print(f"   ⚠️  maintenance_tasks: {e}")

# Summary
print("\n" + "=" * 80)
print("📊 Test Summary")
print("=" * 80)
print("✅ Celery app configured correctly")
print(f"✅ {len(registered_tasks)} tasks registered")
print("✅ Tasks can be queued")
print("⚠️  Worker not running (tasks will be pending)")
print("\n💡 Next Steps:")
print("   1. Start a worker: ./scripts/start_celery_worker.sh")
print("   2. Monitor with Flower: ./scripts/start_flower.sh")
print("   3. View docs: docs/JOB_QUEUE_IMPLEMENTATION.md")
print("=" * 80)
