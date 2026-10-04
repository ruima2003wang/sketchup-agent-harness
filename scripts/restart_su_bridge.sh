#!/bin/bash
# Restart su_bridge - cleans up and restarts the server

BRIDGE_HOST="${SU_BRIDGE_HOST:-127.0.0.1}"
BRIDGE_PORT="${SU_BRIDGE_PORT:-9877}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== su_bridge Restart Script ==="

# The bridge listens on loopback TCP; stopping the server releases the port.
echo "TCP endpoint: tcp://$BRIDGE_HOST:$BRIDGE_PORT"

echo ""
echo "To restart su_bridge in SketchUp Ruby Console:"
echo ""
echo "  # First cleanup (removes cached constants):"
echo "  load '$SCRIPT_DIR/cleanup_su_bridge.rb'"
echo ""
echo "  # Then start fresh:"
echo "  load '$SCRIPT_DIR/../su_bridge/lib/su_bridge.rb'"
echo "  SuBridge.start"
echo ""
echo "Or run all in one:"
echo "  load '$SCRIPT_DIR/cleanup_su_bridge.rb'; load '$SCRIPT_DIR/../su_bridge/lib/su_bridge.rb'; SuBridge.start"
