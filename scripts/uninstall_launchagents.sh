#!/bin/bash
# Uninstall Celery LaunchAgents

set -e

LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

echo "Uninstalling Celery LaunchAgents..."

# Unload services
echo "Stopping services..."
launchctl unload "$LAUNCH_AGENTS_DIR/com.notely.celery.plist" 2>/dev/null || true
launchctl unload "$LAUNCH_AGENTS_DIR/com.notely.celery-beat.plist" 2>/dev/null || true

# Remove plist files
echo "Removing plist files..."
rm -f "$LAUNCH_AGENTS_DIR/com.notely.celery.plist"
rm -f "$LAUNCH_AGENTS_DIR/com.notely.celery-beat.plist"

echo ""
echo "Uninstallation complete!"
echo "Services will no longer start automatically."
echo ""
