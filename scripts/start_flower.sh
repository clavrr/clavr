#!/bin/bash
# Start Flower Monitoring UI
# Usage: ./scripts/start_flower.sh

set -e

PORT="${FLOWER_PORT:-5555}"
BASIC_AUTH="${FLOWER_BASIC_AUTH:-admin:password}"

echo "🌸 Starting Flower Monitoring UI..."
echo "   Port: $PORT"
echo "   URL: http://localhost:$PORT"
echo "   Auth: $BASIC_AUTH"
echo ""

# Start Flower
celery -A src.workers.celery_app flower \
    --port=$PORT \
    --basic_auth=$BASIC_AUTH
