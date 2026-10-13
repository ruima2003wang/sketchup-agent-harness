---
name: exterior-facade
description: Build exterior massing and curtain-wall facades from a reference image or given dimensions.
---

# Exterior Facade Skill

## Purpose

Model a building exterior from a reference image (or from dimensions the user gives): massing
volumes first, then parameterized curtain-wall facades, then materials, then look at the render
and correct. The point is that the model chooses parameters from the image and the generator
produces the geometry — never place mullions one by one.

## Tools

- `create_exterior` — **the one call that builds the whole building**: pass the parameter spec
  (elements + camera) and get every volume, facade grid, band and column in one shot, plus the
  checklist to compare against the reference. Iterate by editing the spec, not by moving boxes.
- `create_box` — single volume when the spec does not cover it (canopies, roof equipment).
- `create_facade_grid` / `create_floor_stack` — one face / one floor band, when only part of the
  model needs them.
- `apply_material` — with `preset` for exterior materials.
- `set_camera_view`, `capture_design`, `save_sketchup_model` — look, compare, deliver.
- `cleanup_model`, `move_entity`, `scale_entity`, `copy_entity` — correct and repeat.

Facade material presets: `glass_dark`, `glass_mid`, `glass_light`; frame presets:
`frame_white`, `frame_light_gray`, `metal_gray`, `panel_dark`, `panel_wood`, `stone_light`,
`concrete`. Glass is opaque in SketchUp today (no alpha support in the bridge).

## Spec shape

```json
{"elements": [
  {"kind": "tower", "id": "tower_a", "x": 20000, "y": 3000, "width": 20000, "depth": 16000,
   "floors": 19, "floor_height": 3600, "bays_x": 8, "bays_y": 6, "base_ring_z": 9000},
  {"kind": "podium", "x": 0, "y": 0, "width": 70000, "depth": 20000, "floors": 2,
   "floor_height": 4500, "bays": 20, "glazed_ground": true, "parapet": true},
  {"kind": "ribbon_block", "x": -30000, "y": 0, "width": 28000, "depth": 16000, "floors": 3,
   "floor_height": 3600, "ribbon_levels": [2, 3],
   "panel": {"width": 16000, "height": 3200, "offset_x": 4000}},
  {"kind": "colonnade", "x_start": 2000, "y": 300, "count": 10, "spacing": 6500,
   "size": 700, "height": 4500}],
 "camera": {"eye": [-70000, -112000, 42000], "target": [17000, 8000, 28000]}}
```

## Parameter table (defaults to read from the image or ask the user)

| Building type | Floor height (mm) | Bay width (mm) | Typical floors | Mullion (mm) | Transom (mm) | Usual materials |
| --- | --- | --- | --- | --- | --- | --- |
| Office tower (curtain wall) | 3600–4200 | 3000–4500 | 12–40 | 60–120 | 120–200 | glass_dark + frame_white |
| Podium / retail base | 4500–6000 | 6000–9000 | 1–3 | 100–200 | 200–400 | stone_light + glass_mid |
| Residential high-rise | 3000–3300 | 3600–6000 | 10–33 | 80–150 | 150–250 | stone_light + glass_light |
| School / hospital | 3600–4200 | 6000–8400 | 4–8 | 80–150 | 200–300 | stone_light + glass_light |
| Industrial / warehouse | 6000–9000 | 8000–12000 | 1–3 | 100–200 | 200–400 | metal_gray + panel_dark |
| Planning massing block | 3000–4200 | 6000–9000 | by FAR | — | — | concrete / panel_dark |

## Verification ranges (enforced by the tool)

`bays` 1–60, `floors` 1–80, `mullion_width` 30–400 mm, `transom_height` 40–800 mm,
`frame_depth` 20–600 mm, `glass_inset` 0–600 mm; derived `bay_width` 1200–15000 mm and
`floor_height` 2200–8000 mm. A combination outside these fails with a named error — fix the
parameter, do not force it.

## Workflow

1. Read the image; write down: number of towers, relative heights, floor rows on the glass,
   podium floors, colonnade spacing, material split (dark glass / white frame / gray ground).
2. Confirm or ask for one real dimension (total height, floors, or footprint). Without it the
   result is scale-assumed and must be reported as such.
3. Fill the spec: one element per volume, `bays` ≈ width / 2500 mm, `floors` =
   rounds(height / floor_height). Call `create_exterior` **once**.
4. `capture_design`, then walk the returned `checklist` against the image line by line:
   floor rows, bay rhythm, band positions, colonnade spacing, material split.
5. Fix the spec (numbers only — never move single boxes) and call `create_exterior` again.
   Two rounds is the normal budget; stop when the checklist matches.
6. `save_sketchup_model` and report assumptions (scale, floors, bay width) plus what is
   massing-level rather than measured.

## Boundaries

- A perspective photo gives proportion and style, not dimensions: never present the result as
  measured. Say which numbers were assumed.
- Facade grids are massing-level: no mullion profiles, no glass panes split per bay, no
  transparency, no photoreal lighting. Say so when handing over.
