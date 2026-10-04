"""Tests for socket bridge module."""

import pytest
import json
import time
from mcp_server.bridge.socket_bridge import (
    DEFAULT_BRIDGE_HOST,
    DEFAULT_BRIDGE_PORT,
    SocketBridge,
    SyncSocketBridge,
    BridgeConfig,
    PingResult,
    ConnectionState,
    create_bridge,
)


class TestBridgeConfig:
    def test_default_config(self):
        config = BridgeConfig()
        assert config.host == DEFAULT_BRIDGE_HOST == "127.0.0.1"
        assert config.port == DEFAULT_BRIDGE_PORT == 9877
        assert config.connect_timeout == 5.0
        assert config.recv_timeout == 30.0
        assert config.max_retries == 3

    def test_default_address_is_loopback_tcp(self):
        config = BridgeConfig()
        assert config.address == "tcp://127.0.0.1:9877"

    def test_custom_config(self):
        config = BridgeConfig(
            host="127.0.0.2",
            port=9999,
            connect_timeout=10.0,
            recv_timeout=60.0,
        )
        assert config.host == "127.0.0.2"
        assert config.port == 9999
        assert config.connect_timeout == 10.0
        assert config.recv_timeout == 60.0


class TestPingResult:
    def test_successful_ping(self):
        result = PingResult(success=True, latency_ms=5.5)
        assert result.success is True
        assert result.latency_ms == 5.5
        assert result.error is None

    def test_failed_ping(self):
        result = PingResult(success=False, error="Connection refused")
        assert result.success is False
        assert result.error == "Connection refused"
        assert result.latency_ms is None


class TestConnectionState:
    def test_states(self):
        assert ConnectionState.DISCONNECTED.value == "disconnected"
        assert ConnectionState.CONNECTING.value == "connecting"
        assert ConnectionState.CONNECTED.value == "connected"
        assert ConnectionState.HANDSHAKE.value == "handshake"


class TestSocketBridge:
    def test_initial_state(self):
        bridge = SocketBridge()
        assert bridge.state == ConnectionState.DISCONNECTED
        assert bridge.is_connected is False

    def test_config_passed_to_constructor(self):
        config = BridgeConfig(host="127.0.0.1", port=1234)
        bridge = SocketBridge(config)
        assert bridge._config.host == "127.0.0.1"
        assert bridge._config.port == 1234

    def test_factory_function_defaults_to_tcp(self):
        bridge = create_bridge()
        assert bridge._config.host == "127.0.0.1"
        assert bridge._config.port == 9877
        assert isinstance(bridge, SocketBridge)

    def test_factory_function_custom_endpoint(self):
        bridge = create_bridge(host="127.0.0.1", port=4567)
        assert bridge._config.port == 4567


class TestSyncSocketBridge:
    def test_inherits_from_socket_bridge(self):
        bridge = SyncSocketBridge()
        assert isinstance(bridge, SocketBridge)


class TestTcpRoundTrip:
    def test_send_over_loopback_tcp(self):
        """The client speaks JSON lines over a loopback TCP server."""
        import socket as socket_module
        import threading

        server = socket_module.socket(socket_module.AF_INET, socket_module.SOCK_STREAM)
        server.setsockopt(socket_module.SOL_SOCKET, socket_module.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]

        received = {}

        def serve_once():
            conn, _ = server.accept()
            try:
                data = conn.recv(65536)
                received["request"] = json.loads(data.decode("utf-8"))
                conn.sendall(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"status": "pong"}}).encode("utf-8"))
            finally:
                conn.close()
                server.close()

        thread = threading.Thread(target=serve_once)
        thread.start()
        try:
            bridge = SocketBridge(BridgeConfig(host="127.0.0.1", port=port))
            response = bridge.send({"jsonrpc": "2.0", "method": "ping", "id": 1})
            bridge.disconnect()
        finally:
            thread.join(timeout=5)

        assert response["result"]["status"] == "pong"
        assert received["request"]["method"] == "ping"
