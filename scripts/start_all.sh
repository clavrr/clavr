#!/bin/bash
# Complete System Startup Script
# Starts all required services for notely-agent

set -e  # Exit on error

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$SCRIPT_DIR/.."

echo "═══════════════════════════════════════════════════════════"
echo "🚀 Starting Notely Agent System"
echo "═══════════════════════════════════════════════════════════"

# 1. Check Redis is running
echo ""
echo "1️⃣  Checking Redis..."
if ! redis-cli ping > /dev/null 2>&1; then
    echo "❌ Redis is not running!"
    echo "   Start Redis with: redis-server"
    echo "   Or on macOS: brew services start redis"
    exit 1
fi
echo "✅ Redis is running"

# 2. Check PostgreSQL is running
echo ""
echo "2️⃣  Checking PostgreSQL..."
if ! pg_isready > /dev/null 2>&1; then
    echo "❌ PostgreSQL is not running!"
    echo "   Start PostgreSQL with your system's service manager"
    echo "   macOS: brew services start postgresql"
    exit 1
fi
echo "✅ PostgreSQL is running"

# 3. Start Celery Worker
echo ""
echo "3️⃣  Starting Celery Worker..."
"$SCRIPT_DIR/start_celery.sh"

# Wait for worker to fully start
sleep 3

# Verify Celery is running
if [ ! -f "$PROJECT_DIR/logs/celery.pid" ]; then
    echo "❌ Celery worker failed to start!"
    exit 1
fi

CELERY_PID=$(cat "$PROJECT_DIR/logs/celery.pid")
if ! ps -p $CELERY_PID > /dev/null 2>&1; then
    echo "❌ Celery worker process not found!"
    exit 1
fi
echo "✅ Celery worker started (PID: $CELERY_PID)"

# 4. Start Celery Beat (Scheduler)
echo ""
echo "4️⃣  Starting Celery Beat Scheduler..."
"$SCRIPT_DIR/start_celery_beat.sh"

# Wait for beat to fully start
sleep 2

# Verify Celery Beat is running
if [ ! -f "$PROJECT_DIR/logs/celerybeat.pid" ]; then
    echo "❌ Celery Beat failed to start!"
    exit 1
fi

CELERY_BEAT_PID=$(cat "$PROJECT_DIR/logs/celerybeat.pid")
if ! ps -p $CELERY_BEAT_PID > /dev/null 2>&1; then
    echo "❌ Celery Beat process not found!"
    exit 1
fi
echo "✅ Celery Beat started (PID: $CELERY_BEAT_PID)"

# 5. Start FastAPI Server
echo ""
echo "4️⃣  Starting FastAPI Server..."
cd "$PROJECT_DIR"
source email_agent/bin/activate

# Check if server is already running
if lsof -ti:8000 > /dev/null 2>&1; then
    echo "⚠️  Server already running on port 8000"
    echo "   Stop it with: kill \$(lsof -ti:8000)"
    read -p "   Kill existing server and restart? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        kill $(lsof -ti:8000) || true
        sleep 2
    else
        echo "Skipping server start"
    fi
fi

# Start server in background
echo "Starting FastAPI server..."
nohup uvicorn main:app --host 0.0.0.0 --port 8000 --reload > logs/server.log 2>&1 &
SERVER_PID=$!
echo $SERVER_PID > logs/server.pid
echo "✅ FastAPI server started (PID: $SERVER_PID)"

# Wait for server to start
echo "Waiting for server to be ready..."
for i in {1..10}; do
    if curl -s http://localhost:8000/docs > /dev/null 2>&1; then
        echo "✅ Server is ready!"
        break
    fi
    sleep 1
    if [ $i -eq 10 ]; then
        echo "❌ Server did not start in time"
        exit 1
    fi
done

# 6. Health Checks
echo ""
echo "6️⃣  Running Health Checks..."

# Check Celery health
echo -n "   Celery health check... "
CELERY_HEALTH=$(curl -s http://localhost:8000/health/celery || echo "failed")
if echo "$CELERY_HEALTH" | grep -q "healthy"; then
    echo "✅"
else
    echo "❌"
    echo "$CELERY_HEALTH"
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "✅ System Started Successfully!"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "📊 System Status:"
echo "   • Redis:      Running"
echo "   • PostgreSQL: Running"
echo "   • Celery:     Running (PID: $CELERY_PID)"
echo "   • FastAPI:    Running (PID: $SERVER_PID)"
echo ""
echo "🌐 Access Points:"
echo "   • API Docs:   http://localhost:8000/docs"
echo "   • Health:     http://localhost:8000/health/celery"
echo "   • Frontend:   http://localhost:3000"
echo ""
echo "📋 Logs:"
echo "   • Server:     tail -f logs/server.log"
echo "   • Celery:     tail -f logs/celery.log"
echo ""
echo "🛑 Stop All:"
echo "   • ./scripts/stop_all.sh"
echo ""
echo "═══════════════════════════════════════════════════════════"
