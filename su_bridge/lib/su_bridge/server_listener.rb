# frozen_string_literal: true

require "socket"
require "json"
require "time"
require "su_bridge/version"

module SuBridge
  # Non-blocking socket server for receiving JSON-RPC requests.
  # Uses UI.start_timer for deferred execution to keep SketchUp responsive.
  # Features automatic self-healing if socket is disrupted.
  class ServerListener
    BRIDGE_HOST = SuBridge::BRIDGE_HOST
    BRIDGE_PORT = SuBridge::BRIDGE_PORT
    TIMER_INTERVAL = 0.1 # seconds
    PROTOCOL_VERSION = "1.0"
    SERVER_VERSION = "1.0.0"
    RECONNECT_DELAY = 1.0 # seconds before attempting reconnect
    MAX_RECONNECT_ATTEMPTS = 3
    # Bounded waits so a stalled loopback client cannot freeze SketchUp's UI.
    CLIENT_READ_TIMEOUT = 5.0
    CLIENT_WRITE_TIMEOUT = 5.0

    def initialize
      @socket = nil
      @running = false
      @stopped = false  # Added to prevent reconnect attempts after cleanup
      @connected_clients = []
      @last_ping_time = nil
      @reconnect_attempts = 0
      @socket_valid = false
    end

    def start
      return if @running
      return unless defined?(UI) && defined?(UI.start_timer)

      setup_socket
      @running = true
      @reconnect_attempts = 0
      schedule_polling
      puts "[su_bridge] Server started on #{endpoint}"
    end

    def stop
      @running = false
      @stopped = true  # Prevent any reconnect attempts
      @socket_valid = false
      @connected_clients.each(&:close)
      @connected_clients.clear
      close_socket
      puts "[su_bridge] Server stopped"
    end

    def running?
      @running
    end

    private

    def endpoint
      "tcp://#{BRIDGE_HOST}:#{BRIDGE_PORT}"
    end

    def setup_socket
      close_socket

      begin
        @socket = TCPServer.new(BRIDGE_HOST, BRIDGE_PORT)
        @socket.listen(5)
        @socket.autoclose = false
        @socket_valid = true
        @reconnect_attempts = 0
        puts "[su_bridge] Socket ready on #{endpoint}"
      rescue Errno::EADDRINUSE, Errno::EACCES => e
        # Another process (or a previous bridge) already owns the port.
        # Report clearly and stay alive so SketchUp is not disrupted; the
        # reconnect loop will retry while the port is unavailable.
        @socket_valid = false
        @socket = nil
        puts "[su_bridge] Port #{BRIDGE_PORT} is not available (#{e.class}: #{e.message}). " \
             "Close the process using it or set SU_BRIDGE_PORT to a free port."
      rescue => e
        @socket_valid = false
        puts "[su_bridge] Socket setup error: #{e.message}"
        raise
      end
    end

    def close_socket
      if @socket
        begin
          @socket.close
        rescue => e
          puts "[su_bridge] Socket close error: #{e.message}"
        end
        @socket = nil
      end
    end

    def schedule_polling
      return if @stopped  # Don't schedule if stopped
      UI.start_timer(TIMER_INTERVAL, false) do
        poll_socket
        schedule_polling if @running && !@stopped
      end
    end

    def poll_socket
      return unless @running

      # Check if socket needs recreation
      unless socket_healthy?
        handle_socket_disconnect
        return
      end

      begin
        # Check for incoming connections without blocking
        io = IO.select([@socket], nil, nil, 0)
        return unless io && !io[0].empty?

        client = @socket.accept_nonblock
        @connected_clients << client
        handle_client(client)
      rescue IO::EAGAINWaitReadable, Errno::EAGAIN
        # No pending connections - this is normal
      rescue Errno::EBADF, IOError => e
        # Socket was closed or became invalid
        puts "[su_bridge] Socket invalid: #{e.message}"
        handle_socket_disconnect
      rescue => e
        puts "[su_bridge] Error polling socket: #{e.message}"
        # Continue running - don't crash on transient errors
      end
    end

    def socket_healthy?
      return false unless @socket
      return false unless @socket_valid

      # Treat an externally closed listener as unhealthy so it reconnects.
      return false if @socket.closed?

      true
    rescue => e
      puts "[su_bridge] Socket health check failed: #{e.message}"
      @socket_valid = false
      false
    end

    def handle_socket_disconnect
      return if @stopped  # Don't reconnect if stopped
      @socket_valid = false
      close_socket

      if @running && @reconnect_attempts < MAX_RECONNECT_ATTEMPTS
        @reconnect_attempts += 1
        puts "[su_bridge] Attempting reconnect (#{@reconnect_attempts}/#{MAX_RECONNECT_ATTEMPTS})..."

        # Schedule reconnect with delay
        UI.start_timer(RECONNECT_DELAY, false) do
          attempt_reconnect unless @stopped
        end
      elsif @reconnect_attempts >= MAX_RECONNECT_ATTEMPTS
        puts "[su_bridge] Max reconnect attempts reached. Run .start to restart."
      end
    end

    def attempt_reconnect
      return if @stopped  # Don't reconnect if stopped
      return unless @running

      begin
        setup_socket
        puts "[su_bridge] Reconnected successfully"
      rescue => e
        puts "[su_bridge] Reconnect failed: #{e.message}"
        handle_socket_disconnect
      end
    end

    def handle_client(client)
      begin
        request_data = read_client_request(client)
        return if request_data.nil? || request_data.empty?

        request = JSON.parse(request_data)
        response = process_request(request)

        write_client_response(client, response)
      rescue JSON::ParserError => e
        error_response = SuBridge::JsonRpcHandler.error_response(
          -32001,
          "Invalid JSON: #{e.message}",
          request&.dig("id")
        )
        write_client_response(client, error_response)
      rescue Errno::EPIPE, Errno::ECONNRESET, IOError => e
        # Client disconnected - normal behavior
        puts "[su_bridge] Client disconnected: #{e.message}"
      rescue => e
        puts "[su_bridge] Error handling client: #{e.message}"
        error_response = SuBridge::JsonRpcHandler.error_response(
          -32000,
          "Internal error: #{e.message}",
          nil
        )
        begin
          write_client_response(client, error_response)
        rescue => write_error
          puts "[su_bridge] Failed to write error: #{write_error.message}"
        end
      ensure
        client.close unless client.closed?
        @connected_clients.delete(client)
      end
    end

    # Reads one newline-terminated JSON-RPC request from an accepted client.
    # Sockets returned by accept_nonblock are non-blocking on every platform
    # (notably Windows), so a bare read_nonblock can raise WaitReadable before
    # the request arrives. Wait for readability with a bounded timeout instead.
    def read_client_request(client)
      deadline = Time.now + CLIENT_READ_TIMEOUT
      buffer = +""

      loop do
        remaining = deadline - Time.now
        return nil if remaining <= 0

        ready = IO.select([client], nil, nil, remaining)
        return nil unless ready

        chunk = client.read_nonblock(65536, exception: false)
        case chunk
        when :wait_readable
          next
        when nil
          break
        else
          buffer << chunk
          break if buffer.include?("\n")
        end
      end

      buffer
    end

    def write_client_response(client, response)
      payload = JSON.generate(response) + "\n"
      deadline = Time.now + CLIENT_WRITE_TIMEOUT

      until payload.empty?
        remaining = deadline - Time.now
        raise IOError, "client write timed out" if remaining <= 0

        prepared = IO.select(nil, [client], nil, remaining)
        raise IOError, "client write timed out" unless prepared

        written = client.write_nonblock(payload, exception: false)
        next if written == :wait_writable
        raise IOError, "client write failed" if written.nil?

        payload = payload[written..-1] || ""
      end
    end

    def process_request(request)
      method = request["method"]
      id = request["id"]
      params = request["params"] || {}

      case method
      when "ping"
        handle_ping(params, id)
      when "handshake"
        handle_handshake(params, id)
      when "execute_operation"
        handle_execute_operation(params, id)
      else
        SuBridge::JsonRpcHandler.error_response(
          -32000,
          "Unknown method: #{method}",
          id
        )
      end
    end

    def handle_ping(params, id)
      @last_ping_time = Time.now

      SuBridge::JsonRpcHandler.success_response({
        status: "pong",
        server_version: SERVER_VERSION,
        protocol_version: PROTOCOL_VERSION,
        timestamp: params["timestamp"],
        server_time: Time.now.to_f,
        socket_valid: @socket_valid,
      }, id)
    end

    def handle_handshake(params, id)
      client_version = params["client_version"] || "unknown"

      SuBridge::JsonRpcHandler.success_response({
        status: "handshake_complete",
        server_version: SERVER_VERSION,
        protocol_version: PROTOCOL_VERSION,
        client_version: client_version,
      }, id)
    end

    def handle_execute_operation(params, id)
      operation_id = params["operation_id"] || "op_#{SecureRandom.hex(4)}"
      operation_type = params["operation_type"]
      payload = params["payload"] || {}
      rollback_on_failure = params.fetch("rollback_on_failure", true)

      result = CommandDispatcher.new.dispatch_operation(
        operation_id,
        operation_type,
        payload,
        rollback_on_failure
      )

      # Check if dispatch_operation returned an error (unknown operation type)
      if result["jsonrpc"] == "2.0" && result.key?("error")
        return result  # Return error directly
      end

      SuBridge::JsonRpcHandler.success_response(result, id)
    rescue => e
      rollback_status = rollback_on_failure ? "completed" : "skipped"
      error_code = error_code_for(e)

      SuBridge::JsonRpcHandler.error_response(
        error_code,
        e.message,
        id,
        {
          operation_id: operation_id,
          rollback_status: rollback_status,
          model_revision: 1,
        }
      )
    end

    def error_code_for(exception)
      if exception.is_a?(SuBridge::UndoManager::ValidationError)
        -32001
      elsif exception.is_a?(SuBridge::UndoManager::EntityNotFoundError)
        -32004
      elsif exception.is_a?(SuBridge::UndoManager::PermissionError)
        -32005
      elsif exception.is_a?(SuBridge::UndoManager::RollbackError)
        -32002
      else
        -32000
      end
    end
  end
end
