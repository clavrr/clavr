#!/bin/bash
# Celery Worker Stop Script

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$SCRIPT_DIR/.."
LOG_DIR="$PROJECT_DIR/logs"
PID_FILE="$LOG_DIR/celery.pid"

echo "Stopping Celery worker..."

# Stop via PID file
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p $PID > /dev/null 2>&1; then
        echo "Killing Celery worker (PID: $PID)..."
        kill $PID
        sleep 2
        
        # Force kill if still running
        if ps -p $PID > /dev/null 2>&1; then
            echo "Force killing worker..."
            kill -9 $PID
        fi
    fi
    rm -f "$PID_FILE"
fi

# Kill any remaining celery processes
pkill -f "celery.*worker" || true

echo "✅ Celery worker stopped"
