#!/bin/bash
# Start Celery Worker
# Usage: ./scripts/start_celery_worker.sh [options]

set -e

# Default values
LOGLEVEL="${CELERY_LOG_LEVEL:-info}"
CONCURRENCY="${CELERY_CONCURRENCY:-4}"
QUEUES="${CELERY_QUEUES:-email,calendar,indexing,notifications,default}"

echo "🚀 Starting Celery Worker..."
echo "   Log Level: $LOGLEVEL"
echo "   Concurrency: $CONCURRENCY"
echo "   Queues: $QUEUES"
echo ""

# Start worker
celery -A src.workers.celery_app worker \
    --loglevel=$LOGLEVEL \
    --concurrency=$CONCURRENCY \
    -Q $QUEUES \
    --hostname=worker@%h \
    --max-tasks-per-child=1000

