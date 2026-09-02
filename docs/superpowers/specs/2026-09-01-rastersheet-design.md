# RasterSheet Design Specification

Date: 2026-09-01
Status: Approved for planning
Supersedes: `RasterSheet_Blender_Addon_Spec.md` (kept as the original design brief)

## 1. Purpose

RasterSheet is a Blender extension that turns a 3D object into a rasterized
sprite sheet. It rotates the object through a series of angles, renders each
angle as a transparent PNG, packs the frames into a sheet, and writes metadata
for game engines.

Its defining constraint is that it behaves like an exporter, not a modeling
tool: it reads the scene, temporarily evaluates alternate orientations, renders
them, and leaves the `.blend` exactly as it found it.

## 2. Decisions

These were settled during brainstorming and are not open for re-litigation
during implementation.

| Decision | Choice |
|---|---|
| Packaging | Blender extension (`blender_manifest.toml`), `blender_version_min = "4.2.0"`. No `bl_info`. |
| Testing | Fast pytest over a bpy-free core, plus a headless Blender smoke test. |
| V1 scope | The full feature list in section 19 of the original brief, built in phases. |
| Color management | Force `Standard` view transform by default, with a user override. |
| Renderer | A dropdown: Scene (default, no override) / Eevee / Cycles. |
| Architecture | Core/shell split: `core/` never imports `bpy`. |

### 2.1 Dependency note

`mathutils` 5.1.0 and `numpy` 2.4.6 install from PyPI under system Python
3.14.6, which is the same Python version and the same numpy version that
Blender 5.2 LTS ships. Core modules can therefore import `mathutils` and
`numpy` and still be exercised by a plain pytest run. No quaternion or vector
math is reimplemented, and the extension ships no wheels: inside Blender these
modules come from Blender itself, and the PyPI installs are development-only.

## 3. Repository

RasterSheet becomes its own git repository at
`/data/fast/Projects/Tech/Tools/BlenderRasterPlugin`, rather than remaining a
subdirectory of the surrounding `Tech` monorepo.
`/home/yalt/Documents/Projects/Tech/Tools/BlenderRasterPlugin` is a symlink to
the same directory, not a second checkout.

### 3.1 Layout

```
BlenderRasterPlugin/
├── rastersheet/
│   ├── __init__.py              # register() / unregister() only
│   ├── blender_manifest.toml
│   ├── core/                    # must never import bpy
│   │   ├── __init__.py
│   │   ├── angles.py            # frame angle schedule
│   │   ├── rotation.py          # per-frame transform matrices
│   │   ├── framing.py           # projected bounds -> ortho_scale
│   │   ├── layout.py            # sheet geometry
│   │   ├── metadata.py          # JSON document
│   │   ├── godot.py             # .tres text generation
│   │   └── paths.py             # filenames and path sanitizing
│   └── blender/                 # the bpy shell
│       ├── __init__.py
│       ├── properties.py        # PropertyGroup
│       ├── panel.py             # View3D sidebar panel
│       ├── view_ops.py          # Copy From Viewport helper operator
│       ├── operator.py          # rastersheet.render, pre-flight checks
│       ├── snapshot.py          # capture and restore via ExitStack
│       ├── camera.py            # current camera / temporary ortho camera
│       ├── lighting.py          # temporary world construction
│       ├── render.py            # the frame loop
│       ├── packing.py           # image buffer compositing
│       └── export.py            # writes JSON and .tres
├── tests/                       # pytest, core only, no Blender
├── tests_blender/               # headless smoke tests, run under Blender
└── docs/superpowers/specs/
```

### 3.2 Manifest

```toml
schema_version = "1.0.0"
id = "rastersheet"
version = "0.1.0"
name = "RasterSheet"
tagline = "Render a rotating object into a sprite sheet"
maintainer = "Dalton Bailey <daltipolous@gmail.com>"
type = "add-on"
blender_version_min = "4.2.0"
license = ["SPDX:GPL-3.0-or-later"]

[permissions]
files = "Write rendered frames, sprite sheets, and metadata"
```

The GPL license is not a preference. Blender add-ons link against Blender's
Python API and must be GPL-compatible to be distributable.

### 3.3 Development loop

Symlink the `rastersheet/` package into the Blender extensions directory:

```
~/.config/blender/5.2/extensions/user_default/rastersheet
```

Blender then imports it as `bl_ext.user_default.rastersheet`. That is also the
module name the headless smoke test passes to
`bpy.ops.preferences.addon_enable`.

## 4. Core modules

Every core function takes plain data or `mathutils` types and returns the same.
None of them read Blender state, and none of them write files.

### 4.1 `angles.py`

```python
def frame_angles(count: int, start_deg: float, sweep_deg: float,
                 clockwise: bool) -> list[float]
```

Returns `count` angles in radians.

The endpoint convention is explicit because both plausible choices produce a
visible defect if chosen wrongly:

- When `sweep_deg` is a whole multiple of 360, the step is `sweep / count`. The
  final frame therefore stops one step short of wrapping onto frame 0, so a
  looping animation has no duplicated frame.
- Otherwise the sweep is partial (for example a 90 degree arc), the step is
  `sweep / (count - 1)`, and both endpoints are rendered.

`clockwise` negates the angles. `count` must be at least 2, which the operator
validates before calling.

### 4.2 `rotation.py`

```python
def axis_vector(axis: str, base_matrix: Matrix) -> Vector
def frame_matrix(base_matrix: Matrix, axis_world: Vector,
                 angle: float, pivot: Vector) -> Matrix
```

`axis_vector` maps the six enum values to a normalized world-space axis. For
`LOCAL_*` the unit axis is transformed by `base_matrix.to_3x3()`; for `WORLD_*`
it is the world axis itself.

`frame_matrix` returns the object's world matrix for that frame:

```
T(pivot) @ Matrix.Rotation(angle, 4, axis_world) @ T(-pivot) @ base_matrix
```

This deliberately diverges from section 5 of the original brief, which set
`obj.rotation_quaternion`. Composing world matrices gives one code path for
local and world axes, makes the pivot a natural parameter, avoids mutating
`rotation_mode` (and therefore avoids having to restore it), and generalizes
without change to the V2 multi-object case, where each object rotates about a
shared pivot.

Parented children follow their parent normally, because the parent's world
matrix is what changed.

### 4.3 `framing.py`

```python
def required_ortho_scale(corners: list[Vector], camera_matrix: Matrix,
                         frame_matrices: list[Matrix], aspect: float,
                         margin: float) -> float
```

`corners` are the eight bounding-box corners of the depsgraph-evaluated object
in the object's **local** space, which is what `Object.bound_box` returns. Each
frame matrix is a full world matrix, so `frame_matrix @ corner` places the
corner in world space for that frame; the result is brought into camera space
by `camera_matrix.inverted()` and reduced to a width and a height. Passing
world-space corners here would apply the base transform twice.

The temporary camera sets `sensor_fit = 'HORIZONTAL'`, so `ortho_scale` is
unambiguously the horizontal extent of the view in world units. The needed
horizontal extent for one frame is therefore:

```
needed = max(width, height * aspect)
```

with `aspect = resolution_x / resolution_y`. The returned value is the maximum
`needed` across every frame, multiplied by `margin`.

One scale is computed for the entire sheet. A per-frame scale would make the
sprite visibly pump in size as it rotates.

This differs from section 7 of the brief, which computed a required vertical
extent. The two are equivalent; fixing `sensor_fit` removes the ambiguity in
how Blender maps `ortho_scale` onto a non-square image.

Square pixels are assumed. `render.pixel_aspect_x/y` other than 1.0 is out of
scope and is reported by pre-flight as an unsupported configuration.

### 4.4 `layout.py`

```python
def sheet_layout(frame_count: int, columns: int, mode: str,
                 frame_width: int, frame_height: int) -> SheetLayout
```

`mode` is `GRID`, `HORIZONTAL`, or `VERTICAL`. `HORIZONTAL` forces
`columns = frame_count`; `VERTICAL` forces `columns = 1`; `GRID` uses the
requested columns and derives `rows = ceil(frame_count / columns)`.

`SheetLayout` carries `rows`, `columns`, `frame_width`, `frame_height`, the
`mode` it was built with, and a list of per-frame cell rectangles in
**top-left origin** pixel coordinates, which is the convention
every consumer of the metadata uses. Blender's bottom-up pixel buffer is not
this module's concern; the shell performs a single flip.

A ragged final row is left transparent.

### 4.5 `metadata.py`

```python
def build_metadata(image_name: str, layout: SheetLayout,
                   animation_name: str, fps: float, loop: bool,
                   axis: str, start_deg: float, sweep_deg: float,
                   clockwise: bool) -> dict
```

Produces the document in section 8 below.

### 4.6 `godot.py`

```python
def sprite_frames_tres(image_res_path: str, layout: SheetLayout,
                       animation_name: str, fps: float, loop: bool) -> str
```

Pure string generation, and therefore covered by a golden-file test.

### 4.7 `paths.py`

Frame filenames (`<stem>_0001.png`, four-digit zero padding), stem
sanitization, and derivation of the frames directory, sheet path, JSON path,
and `.tres` path from an output directory and stem.

## 5. The Blender shell

### 5.1 Snapshot and restore

`snapshot.py` exposes a context manager built on `contextlib.ExitStack`. Every
mutation registers its own restore callback at the moment it is applied, rather
than being collected into a single dictionary up front. If the render fails
partway through setup, only what was actually changed is unwound, and it is
unwound in reverse order.

Captured and restored:

- `scene.render.engine`
- `scene.render.resolution_x`, `resolution_y`, `resolution_percentage`
- `scene.render.film_transparent`
- `scene.render.filepath`
- `scene.render.image_settings.file_format`, `color_mode`, `color_depth`
- `scene.view_settings.view_transform`, `look`, `exposure`
- `scene.camera`
- `scene.world`
- `obj.matrix_world` for every target object

Temporary datablocks (camera object, camera data, world) are also removed
through the stack, so an aborted run leaves no orphans in `bpy.data`. A removal
that fails anyway is reported rather than swallowed silently, since an orphan
left behind is precisely what this machinery exists to prevent.

Within a group of interdependent attributes the governing one is registered
**last**, so that LIFO unwinding restores it **first**. `color_depth`'s valid
values depend on the current `file_format`, and `look`'s on the current
`view_transform`; restoring a dependent attribute before its governor raises
`TypeError` and leaves that attribute stranded at its temporary value.

The extension does not parent objects, change origins, apply transforms, delete
user cameras, insert keyframes, or alter object hierarchy. Frames are rendered
by explicit per-frame transform assignment, never by Blender's animation
system.

### 5.2 Engine identifiers

The Eevee enum identifier changed across the supported version range:
`BLENDER_EEVEE_NEXT` in 4.2, `BLENDER_EEVEE` in 4.5 and later. The correct
value is resolved at runtime by inspecting

```python
scene.render.bl_rna.properties['engine'].enum_items
```

and preferring `BLENDER_EEVEE`, falling back to `BLENDER_EEVEE_NEXT`. Cycles is
`CYCLES` throughout. Selecting an engine that is unavailable in the running
build is a pre-flight failure, not a crash mid-render.

### 5.3 Camera

**Current Camera.** `scene.camera` is used untouched. If it is `None`,
pre-flight fails with a clear message.

**Auto Orthographic.** A temporary camera object and camera data are created,
linked to the scene collection, and assigned to `scene.camera`.

The view direction comes from explicit **Azimuth** and **Elevation** properties
rather than an inferred "desired view direction". With `azimuth = 0` and
`elevation = 0`, the camera sits on the world `-Y` axis looking toward `+Y`,
which is Blender's front view. The direction vector is:

```
d = (sin(az) * cos(el), -cos(az) * cos(el), sin(el))
```

so `elevation = 90` is a top view and `azimuth = 90` is a right-side view.

The camera is placed at `center + d * distance` where `center` is the evaluated
bounds center and `distance = radius * 4`, and is oriented with
`(center - position).to_track_quat('-Z', 'Y')`. Clipping is set to
`clip_start = max(distance - radius * 2, 0.001)` and
`clip_end = distance + radius * 2`.

`ortho_scale` comes from `core.framing.required_ortho_scale`.

A **Copy From Viewport** operator writes the current 3D viewport's azimuth and
elevation into those two properties, so aiming the camera stays a one-click
operation while the stored values remain explicit and reproducible.

### 5.4 Lighting

Every mode other than `Scene World` builds a temporary world and assigns it to
`scene.world`. The user's world node tree is never edited.

- **Material Preview.** A dynamic enum listing the `.exr` files under
  `bpy.utils.system_resource('DATAFILES', path="studiolights/world")`. The
  chosen file is wired into an Environment Texture node feeding a Background
  node. The enum is populated by listing the directory, not by hardcoding
  filenames, because the set varies by Blender build.
- **Scene World.** No world change at all.
- **Scene Lights.** A temporary world with a black background, so only the
  scene's light objects contribute.
- **Flat / Uniform.** A temporary world with a uniform white background at
  strength 1.0. This is *even ambient lighting*, not unlit shading. True unlit
  output would require overriding every material, which is out of scope.
- **Custom HDRI.** A user-supplied image path plus a strength value.

### 5.5 Render loop

`render.py` exposes the loop as a **generator that yields once per frame**:

```python
def frame_jobs(context, settings, targets, base_matrices, frame_matrices):
    for index, matrices in enumerate(frame_matrices):
        apply(matrices)
        context.view_layer.update()
        render_one(index)
        yield index
```

V1 drives it to completion synchronously inside the operator, reporting
progress through `wm.progress_begin` / `progress_update` / `progress_end`.
`bpy.ops.render.render(write_still=True)` blocks, so the Blender window is
unresponsive during a long bake. Writing the loop as a generator means the
later modal-timer version, with a real progress bar and Esc-to-cancel, is a
wrapper around the same code rather than a rewrite. The modal operator is not
built in V1.

Frames are always written to disk. When "Individual Frames" is enabled they go
to `<output>/<stem>_frames/`; when it is disabled they go to a
`tempfile.mkdtemp()` directory that is removed after packing. Holding every
frame's float buffer in memory is both slower and riskier for large sheets.

### 5.6 Packing

Each frame is loaded with `bpy.data.images.load`, and its pixels are pulled
into a numpy array of shape `(height, width, 4)` with `foreach_get`. The frames
are blitted into a single sheet buffer, which is written back with
`foreach_set` and saved with `image.save()`.

Two mechanical details decide whether the output is correct:

**Colorspace.** Blender applies a colorspace transform when decoding an image
and its inverse when encoding. If the sheet image's colorspace differs from the
frames', every sprite is silently double-transformed. The sheet image is
therefore created with the same `colorspace_settings.name` as the loaded
frames, and is written through `image.save()` honoring `image.file_format`,
never through `scene.render` output. The smoke test proves the round trip is
identity by packing a single-frame sheet and comparing it pixel-for-pixel
against its source frame.

**Row order.** Blender's pixel buffer is bottom-up; `core.layout` emits
top-left-origin rectangles. The conversion `y = sheet_height - rect.y -
rect.height` happens in exactly one place in `packing.py`.

Sheets whose width or height would exceed 16384 pixels are rejected during
pre-flight rather than failing at save time.

### 5.7 Pre-flight validation

The operator validates everything below before mutating any scene state, so a
rejected run touches nothing:

- An active object exists and has renderable geometry.
- `scene.camera` is set, when camera mode is Current Camera.
- Frame count is at least 2 and columns at least 1.
- The output directory exists or can be created, and is writable.
- The resulting sheet is within the 16384 pixel limit.
- The selected render engine is available in this build.
- `pixel_aspect_x` and `pixel_aspect_y` are both 1.0.
- Custom HDRI mode has a readable image path.

One warning, not an error: if the target object has constraints or drivers, its
`matrix_world` is recomputed during depsgraph evaluation and the temporary
rotation will not take effect, producing a sheet of identical frames. The
operator reports this explicitly rather than letting the user discover it in
the output.

## 6. Properties

Defined on a single `RasterSheetSettings` PropertyGroup registered at
`bpy.types.Scene.rastersheet`.

| Property | Type | Default |
|---|---|---|
| `rotation_axis` | enum: LOCAL_X/Y/Z, WORLD_X/Y/Z | `LOCAL_Y` |
| `frame_count` | int, 2..256 | 16 |
| `clockwise` | bool | True |
| `start_angle` | float, `ANGLE` subtype (stores radians, displays degrees) | 0.0 |
| `sweep_angle` | float, `ANGLE` subtype (stores radians, displays degrees) | `radians(360)` |
| `pivot_mode` | enum: ORIGIN, BOUNDS_CENTER | `ORIGIN` |
| `camera_mode` | enum: CURRENT, AUTO_ORTHO | `CURRENT` |
| `azimuth` | float degrees | 0.0 |
| `elevation` | float degrees | 30.0 |
| `camera_margin` | float, min 1.0 | 1.2 |
| `engine_mode` | enum: SCENE, EEVEE, CYCLES | `SCENE` |
| `lighting_mode` | enum: MATERIAL_PREVIEW, SCENE_WORLD, SCENE_LIGHTS, FLAT, CUSTOM_HDRI | `MATERIAL_PREVIEW` |
| `studio_light` | dynamic enum | first entry |
| `hdri_path` | file path | "" |
| `hdri_strength` | float, min 0.0 | 1.0 |
| `view_transform_mode` | enum: STANDARD, SCENE, AGX, FILMIC | `STANDARD` |
| `transparent` | bool | True |
| `resolution_mode` | enum: SCENE, CUSTOM | `SCENE` |
| `resolution_x` | int | 256 |
| `resolution_y` | int | 256 |
| `sheet_mode` | enum: GRID, HORIZONTAL, VERTICAL | `GRID` |
| `columns` | int, min 1 | 4 |
| `output_dir` | dir path | `//sprite_output/` |
| `filename_stem` | string | `sprite` |
| `export_frames` | bool | True |
| `export_sheet` | bool | True |
| `export_json` | bool | True |
| `export_godot` | bool | False |
| `godot_res_prefix` | string | `res://` |
| `animation_name` | string | `spin` |
| `fps` | float, min 0.1 | 12.0 |
| `loop` | bool | True |

The `pivot_mode` property is an addition to the original brief. Rotating about
an object origin that sits away from the mesh makes the sprite orbit within the
frame instead of spinning in place, which is the most common way a tool of this
kind produces unusable output. `BOUNDS_CENTER` uses the evaluated bounds center
as the pivot. Neither setting alters the object's actual origin.

## 7. Panel

A single `VIEW_3D` sidebar panel under the `RasterSheet` category, drawn in the
order of the brief's mockup: Target, Rotation, Camera, Rendering, Sprite Sheet,
Output, Export, and the render button. Sub-blocks are hidden when irrelevant:
azimuth, elevation, margin, and Copy From Viewport appear only in Auto
Orthographic mode; the studio light enum only in Material Preview; HDRI path
and strength only in Custom HDRI; custom width and height only in Custom
resolution mode; columns only in Grid mode; the Godot prefix only when the
Godot export is enabled. Rows is shown as a computed, read-only label.

## 8. Metadata format

```json
{
  "image": "nuke_spin.png",
  "frame_count": 16,
  "columns": 4,
  "rows": 4,
  "frame_width": 256,
  "frame_height": 128,
  "sheet_width": 1024,
  "sheet_height": 512,
  "layout": "GRID",
  "fps": 12,
  "loop": true,
  "animation": "spin",
  "rotation": {
    "axis": "LOCAL_Y",
    "start_angle": 0,
    "sweep_angle": 360,
    "clockwise": true
  }
}
```

The `rotation.rotation_amount` key from the brief is renamed `sweep_angle` to
match the property name, and `clockwise`, `layout`, `animation`, and the sheet
dimensions are added because consumers otherwise have to recompute them.

## 9. Godot export

A `SpriteFrames` resource in `format=3`, one `AtlasTexture` sub-resource per
frame:

```
[gd_resource type="SpriteFrames" load_steps=18 format=3]

[ext_resource type="Texture2D" path="res://nuke_spin.png" id="1_tex"]

[sub_resource type="AtlasTexture" id="AtlasTexture_0"]
atlas = ExtResource("1_tex")
region = Rect2(0, 0, 256, 128)

[resource]
animations = [{
"frames": [{"duration": 1.0, "texture": SubResource("AtlasTexture_0")}],
"loop": true,
"name": &"spin",
"speed": 12.0
}]
```

`load_steps` is `frame_count + 2`. The texture path is
`<godot_res_prefix><stem>.png`, because the output directory is usually not the
Godot project root and a hardcoded `res://<stem>.png` would import broken.

## 10. Error handling

The operator wraps the whole run in the snapshot context manager. On any
exception it reports `{'ERROR'}` with the message and returns `{'CANCELLED'}`;
restoration is guaranteed by the context manager rather than by the error
handler. Validation failures are reported the same way but occur before any
mutation.

## 11. Verification

### 11.1 `tests/` — pytest, system Python, no Blender

- `angles`: both endpoint conventions, both directions, minimum and maximum
  counts, non-zero start angles.
- `rotation`: axis mapping for all six enum values; frame matrices checked
  against analytically known results; pivot handling verified by rotating an
  off-origin object and asserting its bounds center is stationary.
- `framing`: a unit cube viewed down an axis and rotated 45 degrees requires a
  scale of `sqrt(2)`; margin and aspect are applied correctly; the returned
  scale is the maximum across frames, not the last one.
- `layout`: grid, horizontal, and vertical modes; a ragged final row; cell
  rectangles tile without overlap or gaps.
- `metadata`: the exact document in section 8.
- `godot`: golden-file comparison, including `load_steps` arithmetic.
- `paths`: zero padding, stem sanitizing, derived paths.
- **Boundary guard**: walk the AST of every module under `core/` and fail if
  any of them imports `bpy`. This enforces the architectural rule mechanically
  instead of by convention.

### 11.2 `tests_blender/` — headless Blender

Run as `blender -b -P tests_blender/run_smoke.py`. The script builds its scene
from scratch (a mesh, a camera, a light), enables the extension, sets
properties, and invokes the operator.

Assertions:

- All expected files exist: frames, sheet, JSON, `.tres`.
- Sheet dimensions match `columns * frame_width` by `rows * frame_height`.
- Packing round trip is identity: a single-frame sheet is pixel-identical to
  its source frame, proving no double colorspace transform.
- Scene restoration is complete: `matrix_world`, engine, resolution,
  `film_transparent`, `filepath`, view transform, `scene.camera`, and
  `scene.world` all equal their pre-run values, and `bpy.data` contains no
  leftover camera, camera data, or world.
- A deliberately failing run (an unwritable output path) still restores
  everything. This is the case the ExitStack design exists for.
- Auto Orthographic framing keeps the object inside the frame at every angle:
  sampled frames have no non-transparent pixels touching the border.

The runner writes its output to a log file and the harness echoes `$?`. Piping
the run through `tail` would return `tail`'s exit code and mask a failure.

### 11.3 Manual verification

Every phase ends with the extension being run interactively in Blender on a
real `.blend`, not only with a green test run. Passing tests are necessary but
not sufficient evidence that a phase is done.

## 12. Phases

Each phase is independently usable.

1. **Scene safety and the frame loop.** Package skeleton, manifest,
   `core.angles`, `core.rotation`, `core.paths`, `snapshot.py`, `properties`,
   a minimal panel, the operator with pre-flight checks, and the render loop
   producing individual PNG frames with the current camera. Verifies the
   central promise first: the scene comes back untouched, including after a
   failure.
2. **Packing.** `core.layout` and `packing.py`, producing the sheet PNG in
   grid, horizontal, and vertical modes.
3. **Auto orthographic camera.** `core.framing` and `camera.py`, including
   azimuth/elevation and Copy From Viewport.
4. **Render configuration.** Engine dropdown with runtime identifier
   resolution, view transform override, and the five lighting modes.
5. **Exporters.** `core.metadata`, `core.godot`, and `export.py`.

## 13. Out of scope for V1

Multi-object and collection targets, custom pivot points beyond the two
provided modes, perspective auto-camera, elevation grids and impostor sheets,
automatic cropping and padding, normal/depth/emission passes, Unity and
Aseprite exporters, a modal cancellable render, and non-square pixel aspect
ratios.

## 14. Known risks

- **Constraints and drivers** on the target defeat `matrix_world` assignment.
  Mitigated by a pre-flight warning, not by a fix.
- **Studio light filenames** vary between Blender builds, so the Material
  Preview enum must be populated by directory listing and must degrade
  gracefully when the directory is missing.
- **Angle properties store radians.** Both `start_angle` and `sweep_angle` use
  Blender's `ANGLE` subtype, so the stored value is radians and the UI shows
  degrees, matching the mockup's `360°`. Every consumer converts with
  `math.degrees()` before handing the value to `core.angles`, which takes
  degrees. Note also that `ANGLE_UNSIGNED` is not a valid `FloatProperty`
  subtype on 5.2 and raises at registration.
- **A Python-callback `EnumProperty` reports no `enum_items`.** Introspecting
  `bl_rna.properties["studio_light"].enum_items` returns an empty sequence even
  after the callback has run and populated its cache, so a test must read the
  property and assert against the add-on's own cache instead.
- **`view_transform` cannot be introspected.** Its `enum_items` reports a
  single `NONE` entry because the values come from the OCIO config at runtime.
  The add-on's own view transform enum is therefore a static list of strings
  and assignment is wrapped in `try`/`except`. Verified on 5.2: `Standard`,
  `AgX`, `Filmic`, and `Khronos PBR Neutral` all assign successfully, and the
  factory default is `AgX`.
- **Cycles may be absent** from `render.engine`'s enum, because it ships as an
  add-on that can be disabled. A headless 5.2 run with `--factory-startup`
  reports only `BLENDER_EEVEE`. Pre-flight must treat a missing engine as a
  validation failure.
- **Eevee's enum identifier** differs across the supported version range, so it
  is resolved at runtime.
- **Large sheets** allocate substantial float buffers. Bounded by the 16384
  pixel pre-flight limit.
