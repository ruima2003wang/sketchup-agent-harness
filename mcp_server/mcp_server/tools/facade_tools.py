"""Parameterized facade and floor-stack generators for exterior massing.

The model decides the parameters — floor count, bay count, mullion sizes, materials — and
these planners turn them into concrete box payloads. The MCP tools in ``server.py`` send
those payloads through the existing ``create_box`` / ``apply_material`` bridge operations,
so the whole generator runs on the operations the bridge already supports.

Keeping the geometry here (pure functions, no bridge, no SketchUp) means the parameter
table and its validation are testable offline, and the same plan can be replayed.
"""

from __future__ import annotations

from typing import Any

# --------------------------------------------------------------------------------------
# Exterior material presets (name -> color). Colors are the only thing the bridge's
# apply_material accepts today; transparency would need a Ruby-side change (material.alpha)
# plus a bridge reinstall/reload, so facade glass stays opaque here.
# --------------------------------------------------------------------------------------
EXTERIOR_MATERIAL_PRESETS: dict[str, dict[str, str]] = {
    "glass_dark": {"color": "#1F2A33", "description": "dark glass curtain wall"},
    "glass_mid": {"color": "#2E3A42", "description": "mid dark glass"},
    "glass_light": {"color": "#8FA9B8", "description": "light reflective glass"},
    "frame_white": {"color": "#EFEFEC", "description": "white facade frame"},
    "frame_light_gray": {"color": "#D9D9D5", "description": "light gray metal frame"},
    "metal_gray": {"color": "#B9B9B6", "description": "gray metal (columns, railings)"},
    "stone_light": {"color": "#DDDAD2", "description": "light stone or render"},
    "panel_dark": {"color": "#3A3F44", "description": "dark panel"},
    "panel_wood": {"color": "#C4A77D", "description": "wood finish"},
    "concrete": {"color": "#B8B5B0", "description": "fair-faced concrete"},
}

# --------------------------------------------------------------------------------------
# The verification table: the ranges a caller may pass. Derived values (bay width, floor
# height) are checked against their own comfort ranges so a nonsense combination fails
# here with a named error instead of producing a thousand silly boxes.
# --------------------------------------------------------------------------------------
FACADE_LIMITS: dict[str, tuple[float, float]] = {
    "width": (300.0, 400_000.0),
    "height": (300.0, 500_000.0),
    "bays": (1, 60),
    "floors": (1, 80),
    "mullion_width": (30.0, 400.0),
    "transom_height": (40.0, 800.0),
    "frame_depth": (20.0, 600.0),
    "glass_inset": (0.0, 600.0),
}
FACADE_DERIVED_LIMITS: dict[str, tuple[float, float]] = {
    "bay_width": (1_200.0, 15_000.0),
    "floor_height": (2_200.0, 8_000.0),
}

FLOOR_STACK_LIMITS: dict[str, tuple[float, float]] = {
    "width": (300.0, 400_000.0),
    "depth": (300.0, 400_000.0),
    "floors": (1, 80),
    "floor_height": (2_200.0, 8_000.0),
    "slab_thickness": (40.0, 800.0),
    "overhang": (0.0, 5_000.0),
}

# Element-level ranges used by the composite exterior builder.
ELEMENT_LIMITS: dict[str, tuple[float, float]] = {
    "count": (1, 80),
    "crown_height": (300.0, 6_000.0),
    "band_height": (200.0, 6_000.0),
    "parapet_height": (200.0, 3_000.0),
    "spacing": (500.0, 20_000.0),
    "size": (100.0, 3_000.0),
    "height": (300.0, 500_000.0),
    "ribbon_level": (0, 80),
}


class FacadeParameterError(ValueError):
    """A parameter is outside the verified range, or the combination is nonsensical."""


def check_range(name: str, value: float, limits: dict[str, tuple[float, float]]) -> None:
    low, high = limits[name]
    if value < low or value > high:
        raise FacadeParameterError(
            f"{name}={value:g} is outside the verified range {low:g}..{high:g}"
        )


def check_int_range(name: str, value: int, limits: dict[str, tuple[float, float]]) -> None:
    low, high = limits[name]
    if value < low or value > high:
        raise FacadeParameterError(
            f"{name}={value} is outside the verified range {int(low)}..{int(high)}"
        )


def preset_color(preset: str | None) -> str | None:
    """Resolve a material preset name to its color, or None when unknown/absent."""
    if not preset:
        return None
    entry = EXTERIOR_MATERIAL_PRESETS.get(preset.strip())
    return entry["color"] if entry else None


def _box(corner_x: float, corner_y: float, corner_z: float, width: float, depth: float, height: float) -> dict[str, Any]:
    return {
        "corner": [corner_x, corner_y, corner_z],
        "width": width,
        "depth": depth,
        "height": height,
    }


def facade_grid_boxes(
    *,
    origin_x: float,
    origin_y: float,
    origin_z: float,
    width: float,
    height: float,
    axis: str,
    outward: int,
    bays: int,
    floors: int,
    mullion_width: float = 80.0,
    transom_height: float = 140.0,
    frame_depth: float = 60.0,
    glass_inset: float = 90.0,
    floor_scale: bool = True,
) -> dict[str, Any]:
    """Plan one curtain-wall face: a glass plane plus its mullion and transom grid.

    ``axis`` is the direction the facade runs ("x" or "y"); ``outward`` (+1/-1) is the
    side the frame protrudes toward, so the caller can dress all four faces of a mass.
    ``floor_scale=False`` is for partial-height bands (ribbon windows): the bay rhythm
    still applies, but the band is not a full floor, so the floor-height range is not
    checked against it. Returns box payloads ready for the bridge's ``create_box``.
    """
    if axis not in {"x", "y"}:
        raise FacadeParameterError('axis must be "x" or "y"')
    if outward not in {1, -1}:
        raise FacadeParameterError("outward must be 1 or -1")

    check_range("width", float(width), FACADE_LIMITS)
    check_range("height", float(height), FACADE_LIMITS)
    check_range("mullion_width", float(mullion_width), FACADE_LIMITS)
    check_range("transom_height", float(transom_height), FACADE_LIMITS)
    check_range("frame_depth", float(frame_depth), FACADE_LIMITS)
    check_range("glass_inset", float(glass_inset), FACADE_LIMITS)
    check_int_range("bays", int(bays), FACADE_LIMITS)
    check_int_range("floors", int(floors), FACADE_LIMITS)

    bay_width = float(width) / int(bays)
    floor_height = float(height) / int(floors)
    check_range("bay_width", bay_width, FACADE_DERIVED_LIMITS)
    if floor_scale:
        check_range("floor_height", floor_height, FACADE_DERIVED_LIMITS)

    frame_start = float(origin_x) if axis == "x" else float(origin_y)
    frame_plane = float(origin_y) if axis == "x" else float(origin_x)
    frame_depth_signed = float(frame_depth) * (1 if outward > 0 else -1)
    frame_corner = frame_plane if outward > 0 else frame_plane - float(frame_depth)
    recess_corner = frame_plane - float(glass_inset) if outward > 0 else frame_plane

    def oriented(corner_along: float, size_along: float, corner_out: float, size_out: float) -> dict[str, Any]:
        if axis == "x":
            return _box(corner_along, corner_out, float(origin_z), size_along, size_out, float(height))
        return _box(corner_out, corner_along, float(origin_z), size_out, size_along, float(height))

    glass = [
        oriented(
            frame_start,
            float(width),
            recess_corner,
            float(glass_inset) if glass_inset > 0 else float(frame_depth),
        )
    ]

    mullions: list[dict[str, Any]] = []
    for index in range(int(bays) + 1):
        along = frame_start + index * bay_width - float(mullion_width) / 2
        if index == 0:
            along = frame_start
        elif index == int(bays):
            along = frame_start + float(width) - float(mullion_width)
        mullions.append(oriented(along, float(mullion_width), frame_corner, float(frame_depth)))

    transoms: list[dict[str, Any]] = []
    for level in range(int(floors) + 1):
        base = float(origin_z) + level * floor_height - float(transom_height) / 2
        if level == 0:
            base = float(origin_z)
        elif level == int(floors):
            base = float(origin_z) + float(height) - float(transom_height)
        if axis == "x":
            box = _box(
                frame_start,
                frame_corner,
                base,
                float(width),
                float(frame_depth),
                float(transom_height),
            )
        else:
            box = _box(
                frame_corner,
                frame_start,
                base,
                float(frame_depth),
                float(width),
                float(transom_height),
            )
        transoms.append(box)

    return {
        "glass_boxes": glass,
        "frame_boxes": [*mullions, *transoms],
        "mullion_count": len(mullions),
        "transom_count": len(transoms),
        "derived": {
            "bay_width": bay_width,
            "floor_height": floor_height,
            "frame_depth_signed": frame_depth_signed,
        },
        "assumptions": [
            "Massing-level facade: one glass plane plus a mullion/transom grid, not a facade engineering model.",
            "Glass sits recessed behind the frame plane; the frame protrudes by frame_depth.",
        ],
        "quality_flags": ["facade_grid_generated"],
    }


def floor_stack_boxes(
    *,
    origin_x: float,
    origin_y: float,
    origin_z: float,
    width: float,
    depth: float,
    floors: int,
    floor_height: float,
    slab_thickness: float = 200.0,
    overhang: float = 0.0,
) -> dict[str, Any]:
    """Plan a stack of floor slabs (and the roof slab) for one footprint."""
    check_range("width", float(width), FLOOR_STACK_LIMITS)
    check_range("depth", float(depth), FLOOR_STACK_LIMITS)
    check_range("floor_height", float(floor_height), FLOOR_STACK_LIMITS)
    check_range("slab_thickness", float(slab_thickness), FLOOR_STACK_LIMITS)
    check_range("overhang", float(overhang), FLOOR_STACK_LIMITS)
    check_int_range("floors", int(floors), FLOOR_STACK_LIMITS)

    slabs: list[dict[str, Any]] = []
    for level in range(1, int(floors) + 1):
        top = float(origin_z) + level * float(floor_height)
        slabs.append(
            _box(
                float(origin_x) - float(overhang),
                float(origin_y) - float(overhang),
                top - float(slab_thickness),
                float(width) + 2 * float(overhang),
                float(depth) + 2 * float(overhang),
                float(slab_thickness),
            )
        )

    return {
        "slab_boxes": slabs,
        "slab_count": len(slabs),
        "derived": {
            "total_height": int(floors) * float(floor_height),
            "level_count": int(floors),
        },
        "assumptions": [
            "Slabs are massing bands at each floor level (plus the roof), not a structural model.",
        ],
        "quality_flags": ["floor_stack_generated"],
    }
