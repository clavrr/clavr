#!/bin/bash
# Start Celery Beat scheduler for periodic tasks
# This enables automatic incremental email syncing every 30 minutes
# Usage: ./scripts/start_celery_beat.sh

set -e

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Starting Celery Beat scheduler...${NC}"

# Create logs directory if it doesn't exist
mkdir -p logs

# Check if Beat is already running
if [ -f logs/celerybeat.pid ]; then
    PID=$(cat logs/celerybeat.pid)
    if ps -p $PID > /dev/null 2>&1; then
        echo -e "${YELLOW}⚠️  Celery Beat is already running (PID: $PID)${NC}"
        echo -e "${YELLOW}   Stop it first with: ./scripts/stop_celery_beat.sh${NC}"
        exit 1
    else
        echo -e "${YELLOW}Removing stale PID file${NC}"
        rm logs/celerybeat.pid
    fi
fi

# Check if Celery worker is running
if [ ! -f logs/celery.pid ]; then
    echo -e "${RED}❌ Celery worker is not running!${NC}"
    echo -e "${YELLOW}   Start it first with: ./scripts/start_celery.sh${NC}"
    exit 1
fi

LOGLEVEL="${CELERY_LOG_LEVEL:-info}"

# Start Celery Beat
echo -e "${GREEN}📅 Starting Celery Beat scheduler...${NC}"
echo -e "${GREEN}   Log Level: $LOGLEVEL${NC}"
celery -A src.workers.celery_app beat \
    --loglevel=$LOGLEVEL \
    --logfile=logs/celerybeat.log \
    --pidfile=logs/celerybeat.pid \
    --schedule=logs/celerybeat-schedule \
    --detach

# Wait a moment for Beat to start
sleep 2

# Check if Beat started successfully
if [ -f logs/celerybeat.pid ]; then
    PID=$(cat logs/celerybeat.pid)
    if ps -p $PID > /dev/null 2>&1; then
        echo -e "${GREEN}✅ Celery Beat started successfully (PID: $PID)${NC}"
        echo -e "${GREEN}   📋 Logs: tail -f logs/celerybeat.log${NC}"
        echo -e "${GREEN}   📅 Scheduled tasks:${NC}"
        echo -e "${GREEN}      - Incremental email sync: every 30 minutes${NC}"
        echo -e "${GREEN}      - Email sync: every 5 minutes${NC}"
        echo -e "${GREEN}      - Session cleanup: hourly${NC}"
        echo -e "${GREEN}      - Cache stats: hourly${NC}"
    else
        echo -e "${RED}❌ Failed to start Celery Beat${NC}"
        echo -e "${YELLOW}   Check logs: tail -f logs/celerybeat.log${NC}"
        exit 1
    fi
else
    echo -e "${RED}❌ Failed to start Celery Beat${NC}"
    echo -e "${YELLOW}   Check logs: tail -f logs/celerybeat.log${NC}"
    exit 1
fi

