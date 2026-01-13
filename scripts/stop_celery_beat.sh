#!/bin/bash
# Stop Celery Beat scheduler
# Usage: ./scripts/stop_celery_beat.sh

set -e

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Stopping Celery Beat scheduler...${NC}"

# Check if PID file exists
if [ ! -f logs/celerybeat.pid ]; then
    echo -e "${YELLOW}⚠️  Celery Beat is not running (no PID file found)${NC}"
    exit 0
fi

# Read PID from file
PID=$(cat logs/celerybeat.pid)

# Check if process is running
if ! ps -p $PID > /dev/null 2>&1; then
    echo -e "${YELLOW}⚠️  Celery Beat process not found (stale PID file)${NC}"
    rm logs/celerybeat.pid
    exit 0
fi

# Stop Celery Beat
echo -e "${GREEN}Stopping Celery Beat (PID: $PID)...${NC}"
kill -TERM $PID

# Wait for process to stop
TIMEOUT=10
COUNTER=0
while ps -p $PID > /dev/null 2>&1 && [ $COUNTER -lt $TIMEOUT ]; do
    sleep 1
    COUNTER=$((COUNTER + 1))
done

# Force kill if still running
if ps -p $PID > /dev/null 2>&1; then
    echo -e "${YELLOW}Forcing shutdown...${NC}"
    kill -KILL $PID
    sleep 1
fi

# Remove PID file
rm -f logs/celerybeat.pid

echo -e "${GREEN}✅ Celery Beat stopped successfully${NC}"
