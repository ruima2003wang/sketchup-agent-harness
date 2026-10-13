"""Tests for the one-call exterior builder (planner and MCP tool)."""

import json

import pytest

from mcp_server.tools.exterior_plan import build_exterior_plan
from mcp_server.tools.facade_tools import EXTERIOR_MATERIAL_PRESETS, FacadeParameterError

SPEC = {
    "elements": [
        {
            "kind": "tower",
            "id": "tower_a",
            "x": 20_000,
            "y": 3_000,
            "width": 20_000,
            "depth": 16_000,
            "floors": 19,
            "floor_height": 3_600,
            "bays_x": 8,
            "bays_y": 6,
            "base_ring_z": 9_000,
        },
        {
            "kind": "podium",
            "id": "podium",
            "x": 0,
            "y": 0,
            "width": 70_000,
            "depth": 20_000,
            "floors": 2,
            "floor_height": 4_500,
            "bays": 20,
        },
        {
            "kind": "ribbon_block",
            "id": "left",
            "x": -30_000,
            "y": 0,
            "width": 28_000,
            "depth": 16_000,
            "floors": 3,
            "floor_height": 3_600,
            "ribbon_levels": [2],
            "bays": 8,
            "panel": {"width": 16_000, "height": 3_200, "offset_x": 4_000},
        },
        {
            "kind": "colonnade",
            "id": "columns",
            "x_start": 2_000,
            "y": 300,
            "count": 10,
            "spacing": 6_500,
            "size": 700,
            "height": 4_500,
        },
    ],
    "camera": {"eye": [-70_000, -112_000, 42_000], "target": [17_000, 8_000, 28_000]},
}


class FakeBridge:
    """Record requests and answer like the Ruby bridge."""

    def __init__(self):
        self.requests = []
        self.connected = False

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def send(self, request):
        self.requests.append(request)
        operation = request["params"]["operation_type"]
        if operation == "create_box":
            return {"result": {"entity_ids": [f"box_{len(self.requests)}"], "status": "success"}}
        if operation == "apply_material":
            return {"result": {"entity_ids": request["params"]["payload"]["entity_ids"]}}
        return {"result": {"camera_eye": [0, 0, 0], "camera_target": [0, 0, 0]}}


def labels(plan):
    return [box["label"] for box in plan["boxes"]]


def test_plan_builds_every_element_kind_in_one_call():
    plan = build_exterior_plan(SPEC)
    names = labels(plan)

    assert plan["derived"]["element_count"] == 4
    assert plan["derived"]["tallest_element"] == "tower_a"
    assert plan["derived"]["top_z"] == pytest.approx(19 * 3_600.0)
    assert "tower_a_mass" in names
    assert "tower_a_crown" in names
    assert "tower_a_base_ring" in names
    assert "podium_storefront" in names
    assert "podium_parapet" in names
    assert "left_panel" in names
    assert sum(1 for name in names if name.startswith("columns_column_")) == 10
    # Frames are generated per face: two grid calls per axis orientation.
    assert sum(1 for name in names if name.startswith("tower_a_frame_")) == 112
    assert plan["camera"]["eye"][0] == -70_000


def test_plan_reports_a_checklist_to_compare_with_the_image():
    plan = build_exterior_plan(SPEC)
    checklist = "\n".join(plan["checklist"])

    assert "tower_a: 19 floor rows" in checklist
    assert "8 bays on the long face" in checklist
    assert "podium: 2 floors" in checklist
    assert "columns: 10 columns at 6500 mm spacing" in checklist
    assert "dark panel" in checklist


def test_plan_rejects_bad_specs():
    with pytest.raises(FacadeParameterError, match="elements"):
        build_exterior_plan({})
    with pytest.raises(FacadeParameterError, match="kind"):
        build_exterior_plan({"elements": [{"kind": "pagoda"}]})
    with pytest.raises(FacadeParameterError, match="floors"):
        build_exterior_plan(
            {"elements": [{"kind": "tower", "x": 0, "y": 0, "width": 20_000, "depth": 16_000, "floors": 0}]}
        )
    with pytest.raises(FacadeParameterError, match="spacing"):
        build_exterior_plan(
            {
                "elements": [
                    {"kind": "colonnade", "x_start": 0, "y": 0, "count": 2, "spacing": 100, "height": 4_000}
                ]
            }
        )
    with pytest.raises(FacadeParameterError, match="camera"):
        build_exterior_plan({**SPEC, "camera": "behind you"})


@pytest.mark.asyncio
async def test_create_exterior_builds_once_and_applies_each_material_once(monkeypatch):
    from mcp_server import server

    bridge = FakeBridge()
    monkeypatch.setattr(server, "SocketBridge", lambda: bridge)

    response = await server.create_exterior(SPEC)
    data = json.loads(response.text)
    plan = build_exterior_plan(SPEC)

    operations = [request["params"]["operation_type"] for request in bridge.requests]
    assert operations.count("create_box") == len(plan["boxes"])
    assert operations.count("apply_material") == len(data["entities_by_preset"])
    assert operations.count("set_camera_view") == 1
    assert data["status"] == "created"
    assert data["box_count"] == len(plan["boxes"])
    assert data["checklist"]
    assert set(data["entities_by_preset"]) <= set(EXTERIOR_MATERIAL_PRESETS)
    assert data["camera_error"] is None


@pytest.mark.asyncio
async def test_create_exterior_uses_the_preset_colors(monkeypatch):
    from mcp_server import server

    bridge = FakeBridge()
    monkeypatch.setattr(server, "SocketBridge", lambda: bridge)

    await server.create_exterior(SPEC)
    colors = {
        request["params"]["payload"].get("color")
        for request in bridge.requests
        if request["params"]["operation_type"] == "apply_material"
    }

    assert colors <= {entry["color"] for entry in EXTERIOR_MATERIAL_PRESETS.values()}


@pytest.mark.asyncio
async def test_create_exterior_rejects_unknown_preset_before_touching_sketchup(monkeypatch):
    from mcp_server import server

    bridge = FakeBridge()
    monkeypatch.setattr(server, "SocketBridge", lambda: bridge)

    spec = json.loads(json.dumps(SPEC))
    spec["elements"][0]["glass_preset"] = "glass_vibes"
    response = await server.create_exterior(spec)

    assert response.text.startswith("Error:")
    assert "glass_vibes" in response.text
    assert bridge.requests == []


@pytest.mark.asyncio
async def test_create_exterior_reports_partial_creation(monkeypatch):
    from mcp_server import server

    class FailingBridge(FakeBridge):
        def send(self, request):
            if request["params"]["operation_type"] == "create_box" and len(self.requests) >= 4:
                self.requests.append(request)
                return {"error": {"message": "bridge refused the box"}}
            return super().send(request)

    bridge = FailingBridge()
    monkeypatch.setattr(server, "SocketBridge", lambda: bridge)

    response = await server.create_exterior(SPEC)

    assert response.text.startswith("Error:")
    assert "failed" in response.text
