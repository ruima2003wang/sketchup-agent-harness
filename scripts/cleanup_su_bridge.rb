#!/usr/bin/env ruby
# frozen_string_literal: true

# Cleanup script for su_bridge Ruby plugin
# CRITICAL: Must stop server BEFORE removing constants

BRIDGE_HOST = ENV["SU_BRIDGE_HOST"] || "127.0.0.1"
BRIDGE_PORT = (ENV["SU_BRIDGE_PORT"] || "9877").to_i
SU_BRIDGE_ROOT = ENV["SU_BRIDGE_ROOT"] || File.expand_path("../su_bridge/lib", __dir__)

puts "[su_bridge] Cleanup starting..."

# Step 1: CRITICAL - Stop the server FIRST
if defined?(SuBridge) && SuBridge.respond_to?(:stop)
  puts "[su_bridge] Stopping server..."
  SuBridge.stop
  # Wait a moment for timers to settle
  sleep 0.5
end

# Step 2: The TCP listener is released when the server stops; no socket file
# to remove for a loopback TCP transport.
puts "[su_bridge] TCP endpoint released: tcp://#{BRIDGE_HOST}:#{BRIDGE_PORT}"

# Step 3: Clear Ruby load cache
$LOADED_FEATURES.reject! { |f| f.include?("su_bridge") || f.include?("su_bridge/lib") }
puts "[su_bridge] Cleared Ruby load cache"

# Step 4: Remove SuBridge constant and all nested constants
# Must be done AFTER stop() to prevent reconnect attempts
if defined?(SuBridge)
  # Get all nested constants first
  nested = []
  if SuBridge.respond_to?(:constants)
    nested = SuBridge.constants.dup
  end

  # Remove nested constants from the module
  nested.each do |c|
    begin
      SuBridge.send(:remove_const, c) rescue nil
    end
  end

  # Remove the main module
  Object.send(:remove_const, :SuBridge) rescue nil
  puts "[su_bridge] Removed SuBridge constant"
end

# Step 5: Clean global state that might reference old server
# Remove any lingering timer references by clearing related constants
%w[
  ServerListener
  CommandDispatcher
  UndoManager
  EntityManager
  JsonRpcHandler
].each do |const|
  begin
    if Object.const_defined?(const)
      Object.send(:remove_const, const.to_sym) rescue nil
      puts "[su_bridge] Removed: #{const}"
    end
  rescue
  end
end

puts "[su_bridge] Cleanup complete!"
puts ""
puts "[su_bridge] To restart fresh, copy-paste this EXACT sequence:"
puts ""
puts "=" * 60
puts "# Step 1: Load the plugin (this will re-define SuBridge module)"
puts "load '#{SU_BRIDGE_ROOT}/su_bridge.rb', true"
puts ""
puts "# Step 2: Start the server"
puts "SuBridge.start"
puts "=" * 60
