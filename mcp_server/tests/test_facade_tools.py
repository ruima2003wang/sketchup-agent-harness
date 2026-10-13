"""Tests for the facade / floor-stack generators and their MCP tools."""

import json

import pytest

from mcp_server.tools.facade_tools import (
    EXTERIOR_MATERIAL_PRESETS,
    FacadeParameterError,
    facade_grid_boxes,
    floor_stack_boxes,
    preset_color,
)

TOWER_FACADE = dict(
    origin_x=18_000.0,
    origin_y=2_000.0,
    origin_z=0.0,
    width=18_000.0,
    height=58_000.0,
    axis="x",
    outward=-1,
    bays=6,
    floors=16,
)


class FakeBridge:
    """Record every request and answer like the Ruby bridge."""

    def __init__(self, fail_on: str | None = None, fail_at: int | None = None):
        self.requests = []
        self.connected = False
        self.fail_on = fail_on
        self.fail_at = fail_at
        self.created = 0

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def send(self, request):
        self.requests.append(request)
        operation = request["params"]["operation_type"]
        if operation == "create_box":
            self.created += 1
            if self.fail_on == "create_box" and self.created == self.fail_at:
                return {"error": {"message": "bridge refused the box"}}
            return {"result": {"entity_ids": [f"box_{self.created}"], "status": "success"}}
        if operation == "apply_material":
            if self.fail_on == "apply_material":
                return {"error": {"message": "material refused"}}
            return {"result": {"entity_ids": request["params"]["payload"]["entity_ids"]}}
        return {"result": {}}


def test_facade_grid_counts_and_derived_values():
    plan = facade_grid_boxes(**TOWER_FACADE)

    assert len(plan["glass_boxes"]) == 1
    assert plan["mullion_count"] == 7
    assert plan["transom_count"] == 17
    assert len(plan["frame_boxes"]) == 24
    assert plan["derived"]["bay_width"] == pytest.approx(3000.0)
    assert plan["derived"]["floor_height"] == pytest.approx(3625.0)


def test_facade_grid_clamps_end_members_to_the_plane():
    plan = facade_grid_boxes(**TOWER_FACADE)
    mullions = plan["frame_boxes"][:7]

    # outward=-1 runs from origin_y toward y-; the first mullion starts at origin_x.
    assert mullions[0]["corner"][0] == pytest.approx(18_000.0)
    assert mullions[-1]["corner"][0] == pytest.approx(18_000.0 + 18_000.0 - 80.0)
    transoms = plan["frame_boxes"][7:]
    assert transoms[0]["corner"][2] == pytest.approx(0.0)
    assert transoms[-1]["corner"][2] == pytest.approx(58_000.0 - 140.0)


def test_facade_grid_axis_y_swaps_axes():
    plan = facade_grid_boxes(**{**TOWER_FACADE, "axis": "y"})
    glass = plan["glass_boxes"][0]

    # Glass runs along y now, and is recessed in x.
    assert glass["depth"] == pytest.approx(18_000.0)
    assert glass["width"] == pytest.approx(90.0)
    assert glass["corner"][1] == pytest.approx(2_000.0)


def test_facade_grid_rejects_out_of_range_and_nonsense():
    with pytest.raises(FacadeParameterError, match="axis"):
        facade_grid_boxes(**{**TOWER_FACADE, "axis": "z"})
    with pytest.raises(FacadeParameterError, match="outward"):
        facade_grid_boxes(**{**TOWER_FACADE, "outward": 0})
    with pytest.raises(FacadeParameterError, match="bays"):
        facade_grid_boxes(**{**TOWER_FACADE, "bays": 200})
    # 18 m of facade split into 20 bays is 900 mm per bay: below the verified range.
    with pytest.raises(FacadeParameterError, match="bay_width"):
        facade_grid_boxes(**{**TOWER_FACADE, "bays": 20})
    with pytest.raises(FacadeParameterError, match="frame_depth"):
        facade_grid_boxes(**{**TOWER_FACADE, "frame_depth": 5000})


def test_floor_stack_places_slabs_and_roof():
    plan = floor_stack_boxes(
        origin_x=0.0,
        origin_y=0.0,
        origin_z=8000.0,
        width=18_000.0,
        depth=15_000.0,
        floors=16,
        floor_height=3625.0,
        slab_thickness=250.0,
        overhang=150.0,
    )

    assert plan["slab_count"] == 16
    assert plan["derived"]["total_height"] == pytest.approx(16 * 3625.0)
    roof = plan["slab_boxes"][-1]
    assert roof["corner"][2] + roof["height"] == pytest.approx(8000.0 + 16 * 3625.0)
    assert roof["width"] == pytest.approx(18_000.0 + 300.0)


def test_floor_stack_rejects_out_of_range():
    with pytest.raises(FacadeParameterError, match="floor_height"):
        floor_stack_boxes(
            origin_x=0.0,
            origin_y=0.0,
            origin_z=0.0,
            width=1000.0,
            depth=1000.0,
            floors=2,
            floor_height=900.0,
        )


def test_presets_resolve_and_unknown_ones_do_not():
    assert preset_color("glass_dark") == EXTERIOR_MATERIAL_PRESETS["glass_dark"]["color"]
    assert preset_color("nope") is None
    assert preset_color(None) is None


@pytest.mark.asyncio
async def test_create_facade_grid_sends_boxes_and_two_materials(monkeypatch):
    from mcp_server import server

    bridge = FakeBridge()
    monkeypatch.setattr(server, "SocketBridge", lambda: bridge)

    response = await server.create_facade_grid(**TOWER_FACADE)
    data = json.loads(response.text)

    operations = [request["params"]["operation_type"] for request in bridge.requests]
    assert operations.count("create_box") == 25
    assert operations.count("apply_material") == 2
    assert data["status"] == "created"
    assert data["mullion_count"] == 7
    assert data["derived"]["bay_width"] == pytest.approx(3000.0)
    assert len(data["glass_entities"]) == 1
    assert len(data["frame_entities"]) == 24

    materials = [
        request["params"]["payload"]
        for request in bridge.requests
        if request["params"]["operation_type"] == "apply_material"
    ]
    assert materials[0]["color"] == EXTERIOR_MATERIAL_PRESETS["glass_dark"]["color"]
    assert materials[1]["color"] == EXTERIOR_MATERIAL_PRESETS["frame_white"]["color"]
    assert materials[1]["entity_ids"] == data["frame_entities"]


@pytest.mark.asyncio
async def test_create_facade_grid_reports_partial_creation(monkeypatch):
    from mcp_server import server

    bridge = FakeBridge(fail_on="create_box", fail_at=3)
    monkeypatch.setattr(server, "SocketBridge", lambda: bridge)

    response = await server.create_facade_grid(**TOWER_FACADE)

    # The glass plane (1 box) plus two frame boxes were created before the refusal.
    assert response.text.startswith("Error: frame box 2/24 failed")
    assert "created 1 of 24" in response.text


@pytest.mark.asyncio
async def test_create_facade_grid_rejects_unknown_preset(monkeypatch):
    from mcp_server import server

    bridge = FakeBridge()
    monkeypatch.setattr(server, "SocketBridge", lambda: bridge)

    response = await server.create_facade_grid(**{**TOWER_FACADE, "glass_preset": "glass_vibes"})

    assert response.text.startswith("Error:")
    assert "glass_vibes" in response.text
    # Nothing is sent to SketchUp for a preset the table does not know.
    assert bridge.requests == []


@pytest.mark.asyncio
async def test_create_floor_stack_creates_every_slab(monkeypatch):
    from mcp_server import server

    bridge = FakeBridge()
    monkeypatch.setattr(server, "SocketBridge", lambda: bridge)

    response = await server.create_floor_stack(
        origin_x=0.0,
        origin_y=0.0,
        origin_z=8000.0,
        width=18_000.0,
        depth=15_000.0,
        floors=16,
        floor_height=3625.0,
    )
    data = json.loads(response.text)

    assert data["slab_count"] == 16
    assert len(data["slab_entities"]) == 16
    assert data["derived"]["total_height"] == pytest.approx(58_000.0)


@pytest.mark.asyncio
async def test_apply_material_preset_sets_color(monkeypatch):
    from mcp_server import server

    bridge = FakeBridge()
    monkeypatch.setattr(server, "SocketBridge", lambda: bridge)

    await server.apply_material(entity_ids=["1", "2"], preset="metal_gray")
    payload = bridge.requests[0]["params"]["payload"]

    assert payload["color"] == EXTERIOR_MATERIAL_PRESETS["metal_gray"]["color"]


@pytest.mark.asyncio
async def test_apply_material_unknown_preset_names_the_options(monkeypatch):
    from mcp_server import server

    bridge = FakeBridge()
    monkeypatch.setattr(server, "SocketBridge", lambda: bridge)

    response = await server.apply_material(entity_ids=["1"], preset="mahogany")

    assert response.text.startswith("Error:")
    assert "glass_dark" in response.text
    assert bridge.requests == []
