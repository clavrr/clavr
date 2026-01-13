#!/bin/bash
# Celery Worker Startup Script
# This script ensures Celery runs with the correct configuration to avoid segfaults

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$SCRIPT_DIR/.."
VENV_DIR="$PROJECT_DIR/email_agent"
LOG_DIR="$PROJECT_DIR/logs"
PID_FILE="$LOG_DIR/celery.pid"
LOG_FILE="$LOG_DIR/celery.log"

# Create logs directory if it doesn't exist
mkdir -p "$LOG_DIR"

# Activate virtual environment
source "$VENV_DIR/bin/activate"

# Change to project directory
cd "$PROJECT_DIR"

# Kill any existing Celery workers
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p $OLD_PID > /dev/null 2>&1; then
        echo "Stopping existing Celery worker (PID: $OLD_PID)..."
        kill $OLD_PID
        sleep 2
    fi
    rm -f "$PID_FILE"
fi

# Kill any remaining celery processes
pkill -f "celery.*worker" || true
sleep 1

echo "Starting Celery worker with solo pool (prevents segfaults)..."
echo "Log file: $LOG_FILE"
echo "PID file: $PID_FILE"

# Start Celery with solo pool (CRITICAL: prevents Pinecone/OpenAI segfaults)
# --pool=solo: Single-threaded worker, compatible with threading libraries
# --loglevel=info: Detailed logging for debugging
# --logfile: Persistent log file
# --pidfile: Track process ID for management
celery -A src.workers.celery_app worker \
    --pool=solo \
    --loglevel=info \
    --logfile="$LOG_FILE" \
    --pidfile="$PID_FILE" \
    --detach

# Wait a moment for worker to start
sleep 2

# Verify worker started
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p $PID > /dev/null 2>&1; then
        echo "✅ Celery worker started successfully (PID: $PID)"
        echo "   Monitor logs: tail -f $LOG_FILE"
        exit 0
    else
        echo "❌ Celery worker failed to start"
        exit 1
    fi
else
    echo "❌ PID file not created"
    exit 1
fi
