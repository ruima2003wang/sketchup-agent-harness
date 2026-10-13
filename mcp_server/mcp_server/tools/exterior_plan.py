"""One-call exterior builder: a parameter spec in, the whole building out.

The model fills the table (towers, podiums, ribbon blocks, colonnades, materials, camera),
this module turns it into every box, and the response carries the checklist the model uses
to compare its render with the reference image. Iteration means editing the spec and calling
once more — never nudging individual boxes.

Element kinds mirror how exteriors actually read in a photograph:

- ``tower``       a glazed volume: mass, four curtain-wall grids, optional crown and base ring
- ``podium``      a solid base: glazed ground floor, upper mass, glazed top band, parapet
- ``ribbon_block`` a low block: mass, ribbon-window rows on the front, optional dark panel
- ``colonnade``    a row of columns (under a podium overhang, along a facade)
"""

from __future__ import annotations

from typing import Any

from mcp_server.tools.facade_tools import (
    ELEMENT_LIMITS,
    FACADE_LIMITS,
    FLOOR_STACK_LIMITS,
    FacadeParameterError,
    check_int_range,
    check_range,
    facade_grid_boxes,
)

ELEMENT_KINDS = ("tower", "podium", "ribbon_block", "colonnade")

DEFAULT_FLOOR_HEIGHT = 3_600.0
DEFAULT_PRESETS: dict[str, str] = {
    "glass": "glass_dark",
    "frame": "frame_white",
    "solid": "stone_light",
    "column": "metal_gray",
    "panel": "panel_dark",
}


def _number(spec: dict[str, Any], key: str, default: float | None = None) -> float:
    value = spec.get(key, default)
    if value is None:
        raise FacadeParameterError(f"{key} is required")
    return float(value)


def _preset(spec: dict[str, Any], key: str, fallback: str) -> str:
    value = spec.get(key)
    return str(value) if value else fallback


def _box(
    corner: tuple[float, float, float],
    size: tuple[float, float, float],
    preset: str,
    label: str,
) -> dict[str, Any]:
    return {
        "corner": [corner[0], corner[1], corner[2]],
        "width": size[0],
        "depth": size[1],
        "height": size[2],
        "preset": preset,
        "label": label,
    }


def _add_grid(
    boxes: list[dict[str, Any]],
    *,
    x: float,
    y: float,
    z: float,
    width: float,
    depth: float,
    height: float,
    bays_x: int,
    bays_y: int,
    floors: int,
    glass_preset: str,
    frame_preset: str,
    label: str,
    include_glass: bool,
) -> dict[str, float]:
    """Add the four facade grids of a rectangular volume and return derived sizes."""
    faces = (
        ((x, y, z), width, bays_x, "x", -1),
        ((x, y + depth, z), width, bays_x, "x", 1),
        ((x, y, z), depth, bays_y, "y", -1),
        ((x + width, y, z), depth, bays_y, "y", 1),
    )
    derived: dict[str, float] = {}
    for index, (origin, span, bays, axis, outward) in enumerate(faces):
        plan = facade_grid_boxes(
            origin_x=origin[0],
            origin_y=origin[1],
            origin_z=z,
            width=span,
            height=height,
            axis=axis,
            outward=outward,
            bays=bays,
            floors=floors,
        )
        if include_glass:
            for box in plan["glass_boxes"]:
                boxes.append(_box(box["corner"], (box["width"], box["depth"], box["height"]), glass_preset, f"{label}_glass_{index}"))
        for box in plan["frame_boxes"]:
            boxes.append(_box(box["corner"], (box["width"], box["depth"], box["height"]), frame_preset, f"{label}_frame_{index}"))
        derived[f"bay_along_{axis}_{index}"] = plan["derived"]["bay_width"]
    return derived


def _plan_tower(element: dict[str, Any], boxes: list[dict[str, Any]]) -> dict[str, Any]:
    x = _number(element, "x")
    y = _number(element, "y")
    width = _number(element, "width")
    depth = _number(element, "depth")
    z = _number(element, "start_z", 0.0)
    floors = int(element.get("floors", 0))
    floor_height = _number(element, "floor_height", DEFAULT_FLOOR_HEIGHT)
    check_int_range("floors", floors, FACADE_LIMITS)
    check_range("floor_height", floor_height, FLOOR_STACK_LIMITS)
    height = floors * floor_height

    glass_preset = _preset(element, "glass_preset", DEFAULT_PRESETS["glass"])
    frame_preset = _preset(element, "frame_preset", DEFAULT_PRESETS["frame"])
    bays_x = int(element.get("bays_x") or round(width / 2_500))
    bays_y = int(element.get("bays_y") or round(depth / 2_500))
    label = str(element.get("id") or "tower")

    boxes.append(_box((x, y, z), (width, depth, height), glass_preset, f"{label}_mass"))
    derived = _add_grid(
        boxes,
        x=x,
        y=y,
        z=z,
        width=width,
        depth=depth,
        height=height,
        bays_x=bays_x,
        bays_y=bays_y,
        floors=floors,
        glass_preset=glass_preset,
        frame_preset=frame_preset,
        label=label,
        include_glass=False,
    )

    crown_height = float(element.get("crown_height", 1_500.0))
    if element.get("crown", True):
        check_range("crown_height", crown_height, ELEMENT_LIMITS)
        overshoot = float(element.get("band_overshoot", 100.0))
        boxes.append(
            _box(
                (x - overshoot, y - overshoot, z + height - crown_height),
                (width + 2 * overshoot, depth + 2 * overshoot, crown_height),
                frame_preset,
                f"{label}_crown",
            )
        )
    base_ring_z = element.get("base_ring_z")
    if base_ring_z is not None:
        ring_height = float(element.get("band_height", 1_200.0))
        check_range("band_height", ring_height, ELEMENT_LIMITS)
        overshoot = float(element.get("band_overshoot", 100.0))
        boxes.append(
            _box(
                (x - overshoot, y - overshoot, float(base_ring_z)),
                (width + 2 * overshoot, depth + 2 * overshoot, ring_height),
                frame_preset,
                f"{label}_base_ring",
            )
        )

    checklist = [
        f"{label}: {floors} floor rows on the glass, {floor_height:g} mm per floor",
        f"{label}: {bays_x} bays on the long face ({derived.get('bay_along_x_0', 0):g} mm) and {bays_y} on the short face",
    ]
    if element.get("base_ring_z") is not None:
        checklist.append(f"{label}: white ring on the base, crown band at the top ({crown_height:g} mm)")
    return {
        "kind": "tower",
        "id": label,
        "height": height,
        "top_z": z + height,
        "derived": derived,
        "checklist": checklist,
    }


def _plan_podium(element: dict[str, Any], boxes: list[dict[str, Any]]) -> dict[str, Any]:
    x = _number(element, "x")
    y = _number(element, "y")
    width = _number(element, "width")
    depth = _number(element, "depth")
    z = _number(element, "start_z", 0.0)
    floors = int(element.get("floors", 2))
    floor_height = _number(element, "floor_height", 4_500.0)
    check_int_range("floors", floors, FACADE_LIMITS)
    check_range("floor_height", floor_height, FLOOR_STACK_LIMITS)
    height = floors * floor_height
    solid_preset = _preset(element, "solid_preset", DEFAULT_PRESETS["solid"])
    frame_preset = _preset(element, "frame_preset", DEFAULT_PRESETS["frame"])
    glass_preset = _preset(element, "glass_preset", DEFAULT_PRESETS["glass"])
    label = str(element.get("id") or "podium")

    upper_floors = max(floors - 1, 0)
    if upper_floors > 0:
        boxes.append(
            _box((x, y, z + floor_height), (width, depth, upper_floors * floor_height), solid_preset, f"{label}_mass")
        )
    if element.get("glazed_ground", True):
        inset = float(element.get("ground_inset", 1_500.0))
        boxes.append(
            _box(
                (x + inset, y + inset, z),
                (width - 2 * inset, depth - 2 * inset, floor_height),
                _preset(element, "ground_glass_preset", "glass_mid"),
                f"{label}_storefront",
            )
        )
    bays = int(element.get("bays") or round(width / 3_500))
    derived: dict[str, float] = {}
    if upper_floors > 0:
        band_height = float(element.get("band_height", min(2_600.0, floor_height)))
        derived = _add_grid(
            boxes,
            x=x,
            y=y,
            z=z + height - band_height,
            width=width,
            depth=depth,
            height=band_height,
            bays_x=bays,
            bays_y=max(1, round(bays * depth / width)),
            floors=1,
            glass_preset=glass_preset,
            frame_preset=frame_preset,
            label=f"{label}_band",
            include_glass=True,
        )
    if element.get("parapet", True):
        parapet_height = float(element.get("parapet_height", 900.0))
        overshoot = float(element.get("band_overshoot", 400.0))
        boxes.append(
            _box(
                (x, y - overshoot, z + height),
                (width, overshoot if overshoot > 0 else 300.0, parapet_height),
                frame_preset,
                f"{label}_parapet",
            )
        )

    checklist = [f"{label}: {floors} floors, {height:g} mm high"]
    if element.get("glazed_ground", True):
        checklist.append(f"{label}: ground floor glazed and set back (storefront inside the frame)")
    if upper_floors > 0:
        checklist.append(f"{label}: dark glass band under the roof, {bays} bays")
    return {
        "kind": "podium",
        "id": label,
        "height": height,
        "top_z": z + height,
        "derived": derived,
        "checklist": checklist,
    }


def _plan_ribbon_block(element: dict[str, Any], boxes: list[dict[str, Any]]) -> dict[str, Any]:
    x = _number(element, "x")
    y = _number(element, "y")
    width = _number(element, "width")
    depth = _number(element, "depth")
    z = _number(element, "start_z", 0.0)
    floors = int(element.get("floors", 3))
    floor_height = _number(element, "floor_height", DEFAULT_FLOOR_HEIGHT)
    check_int_range("floors", floors, FACADE_LIMITS)
    check_range("floor_height", floor_height, FLOOR_STACK_LIMITS)
    height = floors * floor_height
    solid_preset = _preset(element, "solid_preset", DEFAULT_PRESETS["frame"])
    label = str(element.get("id") or "block")

    boxes.append(_box((x, y, z), (width, depth, height), solid_preset, f"{label}_mass"))
    ribbon_levels = element.get("ribbon_levels") or list(range(max(1, floors - 1), floors + 1))
    bays = int(element.get("bays") or round(width / 3_500))
    for level in ribbon_levels:
        check_int_range("ribbon_level", int(level), ELEMENT_LIMITS)
        if int(level) >= floors:
            continue
        plan = facade_grid_boxes(
            origin_x=x,
            origin_y=y,
            origin_z=z + int(level) * floor_height,
            width=width,
            height=floor_height * 0.45,
            axis="x",
            outward=-1,
            bays=bays,
            floors=1,
            floor_scale=False,
        )
        glass_preset = _preset(element, "glass_preset", "glass_mid")
        for box in plan["glass_boxes"]:
            boxes.append(_box(box["corner"], (box["width"], box["depth"], box["height"]), glass_preset, f"{label}_ribbon_{level}"))
        for box in plan["frame_boxes"]:
            boxes.append(_box(box["corner"], (box["width"], box["depth"], box["height"]), solid_preset, f"{label}_ribbon_{level}"))

    panel = element.get("panel")
    if isinstance(panel, dict):
        panel_width = _number(panel, "width")
        panel_height = _number(panel, "height")
        offset_x = float(panel.get("offset_x", 0.0))
        panel_bottom = float(panel.get("bottom_z", z + floor_height / 2))
        boxes.append(
            _box(
                (x + offset_x, y - 350.0, panel_bottom),
                (panel_width, 350.0, panel_height),
                _preset(panel, "preset", DEFAULT_PRESETS["panel"]),
                f"{label}_panel",
            )
        )

    checklist = [
        f"{label}: {floors} floors, {height:g} mm high",
        f"{label}: ribbon windows on levels {', '.join(str(level) for level in ribbon_levels)}, {bays} bays",
    ]
    if isinstance(panel, dict):
        checklist.append(f"{label}: dark panel {panel.get('width')}x{panel.get('height')} mm on the front")
    return {"kind": "ribbon_block", "id": label, "height": height, "top_z": z + height, "derived": {}, "checklist": checklist}


def _plan_colonnade(element: dict[str, Any], boxes: list[dict[str, Any]]) -> dict[str, Any]:
    x_start = _number(element, "x_start")
    y = _number(element, "y")
    z = _number(element, "start_z", 0.0)
    count = int(element.get("count", 0))
    spacing = _number(element, "spacing")
    size = _number(element, "size", 700.0)
    height = _number(element, "height")
    check_int_range("count", count, ELEMENT_LIMITS)
    check_range("spacing", spacing, ELEMENT_LIMITS)
    check_range("size", size, ELEMENT_LIMITS)
    check_range("height", height, ELEMENT_LIMITS)
    preset = _preset(element, "preset", DEFAULT_PRESETS["column"])
    label = str(element.get("id") or "colonnade")

    for index in range(count):
        boxes.append(
            _box(
                (x_start + index * spacing, y, z),
                (size, size, height),
                preset,
                f"{label}_column_{index}",
            )
        )
    return {
        "kind": "colonnade",
        "id": label,
        "height": height,
        "top_z": z + height,
        "derived": {"count": count, "spacing": spacing},
        "checklist": [
            f"{label}: {count} columns at {spacing:g} mm spacing, {size:g} mm square, {height:g} mm high",
        ],
    }


def build_exterior_plan(spec: dict[str, Any]) -> dict[str, Any]:
    """Turn one parameter spec into every box plus the checklist to compare with the image."""
    if not isinstance(spec, dict):
        raise FacadeParameterError("spec must be an object")
    elements = spec.get("elements")
    if not isinstance(elements, list) or not elements:
        raise FacadeParameterError("elements must be a non-empty list")

    boxes: list[dict[str, Any]] = []
    plan: list[dict[str, Any]] = []
    for element in elements:
        if not isinstance(element, dict):
            raise FacadeParameterError("every element must be an object")
        kind = element.get("kind")
        if kind == "tower":
            plan.append(_plan_tower(element, boxes))
        elif kind == "podium":
            plan.append(_plan_podium(element, boxes))
        elif kind == "ribbon_block":
            plan.append(_plan_ribbon_block(element, boxes))
        elif kind == "colonnade":
            plan.append(_plan_colonnade(element, boxes))
        else:
            raise FacadeParameterError(
                f"unknown element kind {kind!r}; use one of {', '.join(ELEMENT_KINDS)}"
            )

    camera = spec.get("camera")
    if camera is not None and not isinstance(camera, dict):
        raise FacadeParameterError("camera must be an object with eye and target")
    top_z = max((item["top_z"] for item in plan), default=0.0)
    tallest = max(plan, key=lambda item: item["top_z"])

    return {
        "boxes": boxes,
        "elements": plan,
        "derived": {
            "box_count": len(boxes),
            "element_count": len(plan),
            "top_z": top_z,
            "tallest_element": tallest["id"],
        },
        "camera": camera,
        "checklist": [line for item in plan for line in item["checklist"]],
        "assumptions": [
            "Built from the parameter spec the caller read from the reference image.",
            "Massing-level: no facade profiles, no pane-by-pane glass, no photoreal lighting.",
            "Perspective references fix proportions, not dimensions; report assumed scale.",
        ],
        "quality_flags": ["exterior_plan_generated"],
    }
