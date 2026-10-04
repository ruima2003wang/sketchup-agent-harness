#!/bin/bash
# Cleanup script for su_bridge - resets Ruby state for the TCP bridge

BRIDGE_HOST="${SU_BRIDGE_HOST:-127.0.0.1}"
BRIDGE_PORT="${SU_BRIDGE_PORT:-9877}"

echo "=== su_bridge Cleanup Script ==="

# The bridge listens on loopback TCP; the port is released when the server
# stops, so there is no socket file to remove.
echo "TCP endpoint: tcp://$BRIDGE_HOST:$BRIDGE_PORT"

# For SketchUp plugin cache clearing, user needs to run the Ruby script
# inside SketchUp's Ruby Console
echo ""
echo "To fully reset su_bridge in SketchUp:"
echo "1. Open SketchUp Ruby Console"
echo "2. Run:"
echo "   load '/Users/avenir/Code/personal/sketchup-agent-harness/scripts/cleanup_su_bridge.rb'"
echo ""
echo "This will:"
echo "  - Stop the running server"
echo "  - Remove all SuBridge constants (allow clean reload)"
echo "  - Release the TCP endpoint"
echo ""
echo "Then restart with:"
echo "   SuBridge.start"
