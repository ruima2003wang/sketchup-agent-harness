"""Offline contract checks for the Ruby bridge.

The bridge's runtime behavior is covered by RSpec under ``su_bridge/spec``,
which needs a Ruby interpreter. These tests read the Ruby sources directly so a
Python-only checkout still catches contract drift between the MCP server and
the bridge:

* every ``operation_type`` the MCP server sends has a handler in the bridge's
  dispatch table, and every handler in that table is defined;
* the JSON-RPC method the server sends is routed by the bridge listener;
* ``ComponentManager.create_transform`` keeps translation as the outermost
  factor, so rotation and scale never move the placement position.

They verify wiring, not SketchUp behavior. Runtime dispatch is exercised by
``su_bridge/spec/command_dispatch_routing_spec.rb`` and matrix math by
``su_bridge/spec/component_manager_spec.rb``.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BRIDGE_LIB = REPO_ROOT / "su_bridge" / "lib" / "su_bridge"
MCP_PACKAGE = REPO_ROOT / "mcp_server" / "mcp_server"


def _bridge_source(*parts: str) -> str:
    return (BRIDGE_LIB / Path(*parts)).read_text(encoding="utf-8")


def _operation_handlers(source: str) -> dict[str, str]:
    table = re.search(
        r"OPERATION_HANDLERS\s*=\s*\{(?P<body>.*?)\}\s*\.freeze",
        source,
        re.S,
    )
    assert table, "OPERATION_HANDLERS table not found in command_dispatcher.rb"
    entries = re.findall(r'"([a-z0-9_]+)"\s*=>\s*:([a-z0-9_]+)', table.group("body"))
    assert entries, "OPERATION_HANDLERS table is empty"
    return dict(entries)


def _python_operation_types() -> dict[str, set[str]]:
    operations: dict[str, set[str]] = {}
    for path in sorted(MCP_PACKAGE.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(
            r'["\']operation_type["\']\s*:\s*["\']([a-z0-9_]+)["\']',
            source,
        ):
            operations.setdefault(match.group(1), set()).add(
                str(path.relative_to(REPO_ROOT))
            )
    return operations


def _special_operations(source: str, constant: str) -> set[str]:
    block = re.search(
        rf"{constant}\s*=\s*Set\.new\(%w\[(?P<body>.*?)\]\)",
        source,
        re.S,
    )
    assert block, f"{constant} not found in command_dispatcher.rb"
    return set(re.findall(r"[a-z0-9_]+", block.group("body")))


def test_every_operation_the_mcp_server_sends_has_a_bridge_handler():
    handlers = _operation_handlers(_bridge_source("command_dispatcher.rb"))
    operations = _python_operation_types()

    assert operations, "no operation_type literals found in the MCP server"
    missing = {
        operation: sorted(files)
        for operation, files in operations.items()
        if operation not in handlers
    }
    assert not missing, (
        "the MCP server sends operations the Ruby bridge cannot dispatch: "
        f"{missing}"
    )


def test_every_routed_handler_is_defined():
    source = _bridge_source("command_dispatcher.rb")
    handlers = _operation_handlers(source)
    defined = set(re.findall(r"^ {4}def (handle_[a-z0-9_]+)\(", source, re.M))

    missing = sorted(set(handlers.values()) - defined)
    assert not missing, f"dispatch table references undefined methods: {missing}"
    duplicated = [
        handler for handler in set(handlers.values())
        if list(handlers.values()).count(handler) > 1
    ]
    assert not duplicated, f"dispatch table maps several operations to {duplicated}"


def test_transactional_and_entity_modifying_operations_are_routable():
    source = _bridge_source("command_dispatcher.rb")
    handlers = _operation_handlers(source)

    for constant in ("TRANSACTIONAL_OPERATIONS", "ENTITY_MODIFYING_OPERATIONS"):
        unknown = _special_operations(source, constant) - handlers.keys()
        assert not unknown, f"{constant} lists operations without a handler: {unknown}"


def test_execute_operation_is_the_shared_json_rpc_method():
    server_sources = [
        path.read_text(encoding="utf-8")
        for path in sorted(MCP_PACKAGE.rglob("*.py"))
    ]
    assert any('"execute_operation"' in source for source in server_sources), (
        "the MCP server does not send execute_operation requests"
    )

    dispatcher = _bridge_source("command_dispatcher.rb")
    assert 'if method == "execute_operation"' in dispatcher, (
        "CommandDispatcher#dispatch does not route execute_operation"
    )

    listener = _bridge_source("server_listener.rb")
    assert 'when "execute_operation"' in listener, (
        "ServerListener#process_request does not route execute_operation"
    )


def test_unknown_operation_types_get_a_json_rpc_error():
    source = _bridge_source("command_dispatcher.rb")
    start = source.index("handler = OPERATION_HANDLERS[operation_type]")
    guard = source[start:start + 600]

    assert "unless handler" in guard
    assert "Unknown operation_type" in guard
    assert "-32000" in guard


def _ruby_method_body(source: str, signature: str) -> str:
    start = source.index(signature)
    remainder = source[start + len(signature):]
    next_method = re.search(r"\n {6}def ", remainder)
    body = remainder[: next_method.start()] if next_method else remainder
    return re.sub(r"#[^\n]*", "", body)


def test_create_transform_composes_translation_after_rotation_after_scale():
    source = _bridge_source("entities", "component_manager.rb")
    body = _ruby_method_body(
        source,
        "def self.create_transform(position, rotation, scale)",
    )

    factors = re.findall(r"tr\s*=\s*tr\s*\*\s*([a-z_]+)\b", body)
    assert factors == ["rotation_tr", "scale_tr"], (
        "create_transform must multiply rotation and then scale onto the "
        f"translation matrix, found {factors}"
    )

    normalized = re.sub(r"\s+", " ", body)
    assert "tr = Geom::Transformation.new(point)" in normalized, (
        "the translation matrix built from the placement point is missing"
    )
    assert not re.search(r"tr\s*=\s*[a-z_]+\s*\*\s*tr\b", body), (
        "translation must stay the outermost factor so the placement point "
        "is not rotated or scaled"
    )
