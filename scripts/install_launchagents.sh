#!/bin/bash
# Install Celery workers as macOS LaunchAgents
# This ensures they start automatically on system boot and restart if they crash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

echo "Installing Celery workers as LaunchAgents..."
echo "Project directory: $PROJECT_DIR"
echo ""

# Create logs directory if it doesn't exist
mkdir -p "$PROJECT_DIR/logs"

# Stop any running services first
echo "Stopping any existing services..."
launchctl unload "$LAUNCH_AGENTS_DIR/com.notely.celery.plist" 2>/dev/null || true
launchctl unload "$LAUNCH_AGENTS_DIR/com.notely.celery-beat.plist" 2>/dev/null || true
sleep 2

# Create LaunchAgents directory if it doesn't exist
mkdir -p "$LAUNCH_AGENTS_DIR"

# Copy plist files to LaunchAgents directory
echo "Installing Celery worker..."
cp "$SCRIPT_DIR/com.notely.celery.plist" "$LAUNCH_AGENTS_DIR/"
chmod 644 "$LAUNCH_AGENTS_DIR/com.notely.celery.plist"

echo "Installing Celery Beat scheduler..."
cp "$SCRIPT_DIR/com.notely.celery-beat.plist" "$LAUNCH_AGENTS_DIR/"
chmod 644 "$LAUNCH_AGENTS_DIR/com.notely.celery-beat.plist"

# Load the services
echo ""
echo "Loading services..."
launchctl load "$LAUNCH_AGENTS_DIR/com.notely.celery.plist"
launchctl load "$LAUNCH_AGENTS_DIR/com.notely.celery-beat.plist"

# Wait a moment for services to start
sleep 3

# Check status
echo ""
echo "Checking service status..."
echo ""
echo "Celery Worker:"
launchctl list | grep com.notely.celery || echo "  Not running"
echo ""
echo "Celery Beat:"
launchctl list | grep com.notely.celery-beat || echo "  Not running"

echo ""
echo "Installation complete!"
echo ""
echo "Services will now:"
echo "  - Start automatically on system boot"
echo "  - Restart automatically if they crash"
echo "  - Write logs to: $PROJECT_DIR/logs/"
echo ""
echo "Useful commands:"
echo "  Check status:  launchctl list | grep com.notely"
echo "  View logs:     tail -f $PROJECT_DIR/logs/celery.log"
echo "  Stop services: ./scripts/uninstall_launchagents.sh"
echo "  Restart:       launchctl kickstart -k gui/\$(id -u)/com.notely.celery"
echo ""
