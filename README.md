# RasterSheet

RasterSheet is a Blender add-on that turns a 3D object into a rasterized
sprite sheet. Point it at an object in your scene, choose a rotation axis
and frame count, and it will:

- rotate the object through a sweep of angles, one frame at a time
- render each angle to a transparent PNG
- either use the scene's current camera or build a temporary orthographic
  camera that frames the whole rotation automatically
- pack the rendered frames into a single sprite sheet image
- optionally write a JSON metadata sidecar and/or a Godot `SpriteFrames`
  `.tres` resource
- restore the scene to exactly the state it was in before you clicked render

It is aimed at 2D/2.5D games that want pre-rendered, rotatable sprites
(think classic isometric or top-down RPGs) generated from a 3D model
instead of hand-drawn per angle.

## Installing

RasterSheet is packaged as a Blender extension. The installable unit is the
`rastersheet/` directory (it contains `blender_manifest.toml`).

**As a user:**

1. Zip the `rastersheet/` directory so the zip's root contains
   `blender_manifest.toml` directly (not nested one level down).
2. Drag the zip file onto a running Blender window, or use
   Edit → Preferences → Get Extensions → Install from Disk.
3. Enable "RasterSheet" in the extensions list if it isn't enabled
   automatically.

**For development**, symlink the source directory into Blender's extensions
folder instead of zipping/installing on every change:

```bash
scripts/dev_link.sh
```

This links `rastersheet/` into
`~/.config/blender/<version>/extensions/user_default/rastersheet`, so
edits to the source are picked up the next time the add-on is (re)enabled.
Override the target Blender version with `BLENDER_VERSION=4.2
scripts/dev_link.sh` if needed; it defaults to `5.2`.

Once installed and enabled, the panel appears at
**3D View → Sidebar (N-panel) → RasterSheet**.

## Using the panel

Select the object you want to turn into a sprite sheet, make it the active
object, then open the RasterSheet panel. Its controls are grouped into the
following boxes, top to bottom:

**Target** — read-only. Shows the name of the currently active object, or
"No active object" if nothing is selected.

**Rotation** — controls how the object spins between frames:
- *Axis* — which axis to rotate around: the object's own local X/Y/Z, or
  the scene's world X/Y/Z.
- *Pivot* — rotate about the object's origin, or about the center of its
  evaluated bounding box.
- *Frames* — how many frames to render (1–256). One frame is a still:
  the object is rendered once at *Start Angle*, which is what card art and
  icons want.
- *Clockwise* — rotation direction.
- *Start Angle* / *Rotation Amount* — where the sweep begins and how far
  it goes, in degrees (a full turn is the default).

**Camera** — *Current Camera* uses whatever camera is already in the
scene, unmodified. *Auto Orthographic* builds a temporary orthographic
camera positioned by *Azimuth*, *Elevation*, and *Margin* (extra padding
around the object). One camera renders every frame, and it is sized to the
whole rotation at once -- the combined extent of every frame, not just the
widest one -- so a subject that orbits (which is what rotating about an origin
that is not inside the mesh does) stays framed at every angle instead of
swinging out of shot. "Copy From Viewport" sets azimuth/elevation from the
current 3D viewport.

**Rendering** — *Renderer* selects Eevee, Cycles, or leaves the scene's
engine untouched. Eevee's identifier changed between Blender versions, so the
right one is chosen from the running version; Cycles is checked against the
engines actually registered in your build and is only refused when it is
genuinely disabled. *Lighting* selects a bundled studio HDRI (Material
Preview), the scene's own world, scene lights only against a black world,
flat/uniform ambient light, or a custom HDRI file you provide. *View
Transform* selects the color transform applied to the render (Standard,
AgX, Filmic, or the scene's own). *Transparent BG* renders with an alpha
channel. *Resolution* uses either the scene's render resolution or a
custom width/height you set here.

**Stylize** — optional comic/pixel looks, every one **off by default**. With
nothing ticked, rendering is exactly what it was without this box. Tick any
combination:

- *Toon Shading* — flattens lighting into *Bands* hard tiers while keeping
  each material's hue and saturation. **Eevee only** (it is built on Shader
  to RGB); validation refuses it under Cycles. Your materials are never
  edited: the render uses temporary copies swapped into the slots. Pair it
  with *Scene Lights* and a single sun for the cleanest bands; an HDRI gives
  muddier ones. Sub-options, all neutral by default:
  - *Matte* — render metallic materials as non-metallic. Metal has no
    diffuse shading: under one lamp it is black apart from its highlight,
    and under an HDRI it mirrors the HDRI instead of showing its form.
    Usually wanted for toon.
  - *Ignore Surface Detail* — disconnect normal, displacement and roughness
    maps so the bands follow the model's shape instead of breaking into
    speckle. Color textures (the model's paint) are kept.
  - *Brightness* / *Saturation* — scale the bands' on-screen brightness and
    color intensity.
  - *Ink Shadows* — bands at or below this brightness become solid black,
    the large spot blacks of inked comics.
- *Ink Outline (3D)* — inverted-hull ink lines of *Line Width* world units
  around every mesh, which also draws lines where parts overlap. Done with a
  temporary Solidify modifier and material slot, both removed afterward.
  Meshes only.
- *Silhouette Outline (2D)* — a solid ink band *Width* pixels wide around the
  rendered shape's outer edge, drawn behind the subject. The most reliable
  readability win when the sprite is shown small. *Ink Color* is shared
  with the 3D outline.
- *Glow* — a bloom halo around pixels whose brightest channel is above
  *Threshold*, so saturated neon glows as well as white. The halo sits
  behind the subject, so bright colors keep their hue instead of clipping
  to white, and it spills onto a transparent background.
- *Posterize* — reduces each color channel to *Levels* flat values.
- *Pixelate* — averages *Pixel Size* blocks at the same frame size (the sheet
  layout is unchanged); *Hard Edges* snaps alpha to on/off for crisp
  pixel-art edges.

Toon shading and the 3D outline apply to every visible, renderable object in
the scene, not only the rotating target, so a subject built from several
objects comes out in one style. The 2D effects run on each rendered frame
before packing, in a fixed order: posterize, silhouette, glow, pixelate.

**Sprite Sheet** — *Layout* chooses Grid, Horizontal Strip, or Vertical
Strip packing; in Grid mode you also set *Columns* (rows are computed and
shown for reference).

**Output** — *Output Directory* and *Filename* control where files land
and what they're named. *Animation*, *FPS*, and *Loop* are recorded into
the JSON/`.tres` metadata (they don't affect rendering itself).

**Export** — four independent toggles: *Individual Frames* (keep the
per-angle PNGs, not just the packed sheet), *Sprite Sheet* (write the
packed PNG), *Metadata JSON* (write the sidecar described below), and
*Godot .tres* (write a `SpriteFrames` resource; the *Godot Prefix* field
that appears controls the `res://` path baked into it). Godot export
requires the sprite sheet export to also be enabled — RasterSheet checks
this and every other setting before touching disk, and refuses to run if
anything is wrong.

Click **Render Sprite Sheet** to run. **Render Still** renders one image at
*Start Angle* to `<Filename>.png`, ignoring *Frames* and the export toggles
(no frames folder, JSON or `.tres`); every other setting applies as usual.
It writes the same `<Filename>.png` a sprite sheet would, so use a
different *Filename* if you want to keep both.

## Scene safety

RasterSheet never permanently changes your scene. It does not parent
objects, change origins, apply transforms, delete cameras you created, or
alter object hierarchy. Any settings it changes for the duration of the
render — the active object's transform, render engine, resolution, world
lighting, view transform, and (in Auto Orthographic mode) the active
camera — are snapshotted beforehand and restored afterward, whether the
render finishes normally, is cancelled by validation, or fails partway
through.

**The one case that defeats this guarantee:** if the target object's
transform is driven by constraints or drivers, its world matrix is
recomputed from those constraints/drivers every time the scene is
evaluated — so setting `matrix_world` to a rotated pose for a frame has no
visible effect; the constraint or driver puts it right back. RasterSheet
detects this before rendering and reports a warning naming the object, but
it still lets the render proceed (you may want the un-rotated result, or
you may have already accounted for it). If you see this warning and the
frames come out identical, remove or disable the constraint/driver on that
object first.

## Metadata JSON

When *Metadata JSON* is enabled, RasterSheet writes `<stem>.json` next to
the sprite sheet, one document describing exactly the sheet that was
generated:

```json
{
  "image": "nuke_spin.png",
  "frame_count": 16,
  "columns": 4,
  "rows": 4,
  "frame_width": 256,
  "frame_height": 256,
  "sheet_width": 1024,
  "sheet_height": 1024,
  "layout": "GRID",
  "fps": 12.0,
  "loop": true,
  "animation": "spin",
  "rotation": {
    "axis": "LOCAL_Y",
    "start_angle": 0.0,
    "sweep_angle": 360.0,
    "clockwise": true
  }
}
```

Field notes:

- `image` — the sheet's filename (not a path), so the JSON stays portable
  alongside the PNG.
- `frame_width` / `frame_height` — the size of a single frame's cell.
- `sheet_width` / `sheet_height` — the full packed image's dimensions
  (`columns * frame_width`, `rows * frame_height`).
- `layout` — one of `GRID`, `HORIZONTAL`, `VERTICAL`, matching the panel's
  *Layout* setting.
- `rotation.start_angle` and `rotation.sweep_angle` are always in
  **degrees**, regardless of Blender's internal radians representation.

Frame cells are laid out left-to-right, top-to-bottom (row-major), with
frame index 0 at the top-left corner — the same order the `.tres` below
uses, so consumers only need to implement one ordering.

## Using the `.tres` in Godot

When *Godot .tres* is enabled, RasterSheet writes `<stem>.tres`: a Godot 4
`SpriteFrames` resource with one `AtlasTexture` sub-resource per frame,
all referencing the packed sheet via a single `ext_resource`, plus one
named animation. Each frame entry's `duration` is a fixed `1.0` (Godot
weights all frames equally within the animation); the *FPS* setting is
stored as the animation's overall `speed`, and *Loop* is stored as its own
boolean — the three are separate fields, not a computed duration array.

Copy (or symlink) the sheet PNG and the `.tres` into your Godot project,
matching the *Godot Prefix* setting to wherever you place them (e.g. a
prefix of `res://sprites/` expects the files at
`res://sprites/<stem>.png` and `res://sprites/<stem>.tres`). Then:

```gdscript
$AnimatedSprite2D.sprite_frames = preload("res://sprites/nuke_spin.tres")
$AnimatedSprite2D.play("spin")
```

The `.tres` does not embed the animation name into the filename — it's
whatever you set in the *Animation* field, and it's what you pass to
`play()`.

## Running the tests

There are two independent test suites.

**Fast unit tests** (pure Python, no Blender required) cover the `core/`
package — rotation math, sheet layout, metadata/`.tres` generation, paths,
and a boundary check that `core/` never imports `bpy`:

```bash
.venv/bin/pytest
```

**Headless Blender smoke tests** exercise the add-on inside a real
(headless) Blender process — registration, the operator, snapshot/restore,
rendering, camera framing, lighting, and the full export pipeline. Because
a failing run's exit code is meaningless if piped through `grep` or `tail`
(the pipe's exit code wins instead), always redirect to a log file and
check `$?` separately:

```bash
blender -b -P tests_blender/run_smoke.py > /tmp/smoke.log 2>&1; echo "exit=$?"
grep -E "SMOKE|^  ok" /tmp/smoke.log
```

A successful run ends with `SMOKE OK` and exit code 0.
