# frozen_string_literal: true

module SuBridge
  VERSION = "1.0.0"

  # Loopback TCP endpoint used by the bridge on every platform. Windows
  # SketchUp ships a Ruby without AF_UNIX support, so TCP is the portable
  # transport. The host/port can be overridden through the environment.
  BRIDGE_HOST = ENV["SU_BRIDGE_HOST"] || "127.0.0.1"
  BRIDGE_PORT = (ENV["SU_BRIDGE_PORT"] || "9877").to_i
end
