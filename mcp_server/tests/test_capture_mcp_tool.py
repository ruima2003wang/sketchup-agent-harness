"""Tests for capture tools returning standard MCP content blocks."""

import base64
import json

import pytest
from mcp.types import CallToolResult, ImageContent, TextContent

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

CAPTURE_METADATA = {"width": 800, "height": 600, "view_preset": None}


class FakeBridge:
    """Capture the JSON-RPC request and write a PNG like the Ruby bridge."""

    def __init__(self):
        self.request = None
        self.connected = False

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def send(self, request):
        self.request = request
        self.write_png(request)
        return {
            "result": {
                "capture_info": {
                    "output_path": request["params"]["payload"]["output_path"],
                    "width": request["params"]["payload"]["width"],
                    "height": request["params"]["payload"]["height"],
                    "view_preset": request["params"]["payload"]["view_preset"],
                }
            }
        }

    def write_png(self, request):
        with open(request["params"]["payload"]["output_path"], "wb") as handle:
            handle.write(PNG_BYTES)


class MissingFileBridge(FakeBridge):
    """Report a capture without writing the PNG file."""

    def write_png(self, request):
        return None


def assert_metadata_text(text):
    """Assert the capture metadata text carries no path or base64 payload."""
    metadata = json.loads(text)
    assert metadata == CAPTURE_METADATA
    assert "output_path" not in text
    assert "base64" not in text


@pytest.mark.asyncio
async def test_capture_design_returns_metadata_and_image_block(monkeypatch, tmp_path):
    from mcp_server import server

    bridge = FakeBridge()
    monkeypatch.setattr(server, "SocketBridge", lambda: bridge)
    output_path = tmp_path / "view.png"

    result = await server.capture_design(
        output_path=str(output_path),
        width=800,
        height=600,
        return_base64=True,
    )

    assert isinstance(result, CallToolResult)
    assert len(result.content) == 2
    text_part, image_part = result.content
    assert isinstance(text_part, TextContent)
    assert_metadata_text(text_part.text)
    assert isinstance(image_part, ImageContent)
    assert image_part.type == "image"
    assert image_part.mimeType == "image/png"
    assert base64.b64decode(image_part.data) == PNG_BYTES
    assert bridge.request["params"]["payload"]["output_path"] == str(output_path)
    assert output_path.read_bytes() == PNG_BYTES


@pytest.mark.asyncio
async def test_capture_design_without_base64_returns_metadata_only(monkeypatch, tmp_path):
    from mcp_server import server

    bridge = FakeBridge()
    monkeypatch.setattr(server, "SocketBridge", lambda: bridge)

    result = await server.capture_design(
        output_path=str(tmp_path / "view.png"),
        width=800,
        height=600,
    )

    assert isinstance(result, CallToolResult)
    assert len(result.content) == 1
    assert_metadata_text(result.content[0].text)


@pytest.mark.asyncio
async def test_capture_design_reports_unreadable_capture(monkeypatch, tmp_path):
    from mcp_server import server

    bridge = MissingFileBridge()
    monkeypatch.setattr(server, "SocketBridge", lambda: bridge)

    result = await server.capture_design(
        output_path=str(tmp_path / "missing.png"),
        width=800,
        height=600,
        return_base64=True,
    )

    assert len(result.content) == 1
    metadata = json.loads(result.content[0].text)
    assert metadata["width"] == 800
    assert "image_error" in metadata


@pytest.mark.asyncio
async def test_capture_tools_expose_the_image_block_over_mcp(monkeypatch, tmp_path):
    from mcp_server import server

    bridge = FakeBridge()
    monkeypatch.setattr(server, "SocketBridge", lambda: bridge)

    result = await server.mcp.call_tool(
        "capture_design",
        {
            "output_path": str(tmp_path / "view.png"),
            "width": 800,
            "height": 600,
            "return_base64": True,
        },
    )

    assert isinstance(result, CallToolResult)
    assert result.structuredContent is None
    assert [part.type for part in result.content] == ["text", "image"]
    assert result.content[1].mimeType == "image/png"


@pytest.mark.asyncio
async def test_capture_project_snapshot_returns_image_block_and_manifest(
    monkeypatch,
    tmp_path,
):
    from mcp_server import server

    bridge = FakeBridge()
    monkeypatch.setattr(server, "SocketBridge", lambda: bridge)

    result = await server.capture_project_snapshot(
        project_path=str(tmp_path),
        view_preset="top",
        label="review",
        width=800,
        height=600,
        return_base64=True,
    )

    assert len(result.content) == 2
    text_part, image_part = result.content
    payload = json.loads(text_part.text)
    manifest = json.loads((tmp_path / "snapshots" / "manifest.json").read_text())

    assert payload["capture_info"] == {
        "width": 800,
        "height": 600,
        "view_preset": "top",
    }
    assert "output_path" not in text_part.text
    assert "base64" not in text_part.text
    assert payload["snapshot"]["file"].startswith("snapshots/")
    assert image_part.type == "image"
    assert image_part.mimeType == "image/png"
    assert base64.b64decode(image_part.data) == PNG_BYTES
    assert manifest["snapshots"][0]["capture"]["width"] == 800


READ_ONLY_TOOLS = {
    "get_bridge_info",
    "get_component_manifest",
    "get_design_rules",
    "get_designer_profile_status",
    "get_import_summary",
    "get_project_state",
    "get_scene_info",
    "get_selection_info",
    "list_import_sessions",
    "list_local_library_categories",
    "list_project_components",
    "list_project_versions",
    "list_versions",
    "list_visual_feedback",
    "search_components",
    "search_local_library",
}

WRITE_TOOLS = [
    "capture_design",
    "capture_project_snapshot",
    "create_wall",
    "save_sketchup_model",
    "save_project_version",
    "record_render_artifact",
]


@pytest.mark.asyncio
async def test_read_only_tools_carry_read_only_hint():
    from mcp_server import server

    tools = {tool.name: tool for tool in await server.mcp.list_tools()}

    for name in sorted(READ_ONLY_TOOLS):
        annotations = tools[name].annotations
        assert annotations is not None, name
        assert annotations.readOnlyHint is True, name

    for name in WRITE_TOOLS:
        annotations = tools[name].annotations
        assert annotations is None or annotations.readOnlyHint is not True, name
