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

- `create_box` — massing volumes (tower body, podium, low block, columns, crown bands).
- `create_facade_grid` — one facade face: glass plane + vertical mullions + horizontal transoms,
  from `bays` / `floors`. Call it once per face (`axis` "x"/"y", `outward` 1/-1).
- `create_floor_stack` — floor slabs plus roof for exposed bands (podium roofs, terraces, decks).
- `apply_material` — with `preset` for exterior materials.
- `set_camera_view`, `capture_design`, `save_sketchup_model` — look, compare, deliver.
- `cleanup_model`, `move_entity`, `scale_entity`, `copy_entity` — correct and repeat.

Facade material presets: `glass_dark`, `glass_mid`, `glass_light`; frame presets:
`frame_white`, `frame_light_gray`, `metal_gray`, `panel_dark`, `panel_wood`, `stone_light`,
`concrete`. Glass is opaque in SketchUp today (no alpha support in the bridge).

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
3. Massing: one `create_box` per volume, dark glass volumes colored `glass_dark`.
4. Facade: `create_facade_grid` on each visible face. Bay count = floor(width / bay_width);
   floor count = rounds(height / floor_height).
5. Bands: `create_box` for tower crown and base rings (`frame_white`), parapets, and the
   colonnade columns (`metal_gray`).
6. `set_camera_view` to the reference's angle, `capture_design`, then compare with the image:
   proportions, floor rows, band positions, colonnade rhythm. Fix parameters and re-run the
   generator — do not nudge individual boxes.
7. `save_sketchup_model` when the view matches, and report assumptions (scale, floors, bay
   width) plus what is massing-level rather than measured.

## Boundaries

- A perspective photo gives proportion and style, not dimensions: never present the result as
  measured. Say which numbers were assumed.
- Facade grids are massing-level: no mullion profiles, no glass panes split per bay, no
  transparency, no photoreal lighting. Say so when handing over.
