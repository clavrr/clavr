#!/bin/bash
# Stop All Services Script

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$SCRIPT_DIR/.."

echo "🛑 Stopping Notely Agent System..."

# Stop Celery
echo "Stopping Celery worker..."
"$SCRIPT_DIR/stop_celery.sh"

# Stop FastAPI Server
echo "Stopping FastAPI server..."
if [ -f "$PROJECT_DIR/logs/server.pid" ]; then
    SERVER_PID=$(cat "$PROJECT_DIR/logs/server.pid")
    if ps -p $SERVER_PID > /dev/null 2>&1; then
        kill $SERVER_PID
        sleep 2
        if ps -p $SERVER_PID > /dev/null 2>&1; then
            kill -9 $SERVER_PID
        fi
    fi
    rm -f "$PROJECT_DIR/logs/server.pid"
fi

# Kill any remaining server processes
lsof -ti:8000 | xargs kill -9 2>/dev/null || true

echo "✅ All services stopped"
