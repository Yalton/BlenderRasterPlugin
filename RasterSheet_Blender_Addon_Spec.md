# RasterSheet Blender Add-on Spec

## 1. Goal

Create a Blender add-on that converts a 3D object into a rasterized sprite sheet by:

- rotating an object around a chosen local axis
- rendering each rotation as a transparent PNG
- using the current scene camera or an optional generated orthographic camera
- packing rendered frames into a sprite sheet
- optionally exporting metadata for engines such as Godot
- restoring the Blender scene exactly after completion

Working name:

```text
RasterSheet
```

---

## 2. Primary Workflow

User selects an object, then opens:

```text
3D View
→ Sidebar
→ RasterSheet
```

Suggested panel:

```text
RasterSheet

Target
────────────────────────
Object:            [ Nuke        ]

Rotation
────────────────────────
Axis:              [ Local Y ▼ ]
Frames:            [ 16         ]
Direction:         [ Clockwise ▼]
Start Angle:       [ 0°         ]
Rotation Amount:   [ 360°       ]

Camera
────────────────────────
Camera Mode:
  (•) Current Camera
  ( ) Auto Orthographic

Camera Margin:     [ 1.20 ]

Rendering
────────────────────────
Renderer:          [ Eevee ▼ ]
Lighting:
  [ Material Preview ▼ ]

Transparent BG:    [✓]

Resolution:
  (•) Scene Resolution
  ( ) Custom

Width:             [256]
Height:            [128]

Sprite Sheet
────────────────────────
Columns:           [4]
Rows:              Auto (4)

Output Directory:
[ //sprite_output/       ]

Filename:
[ nuke_spin             ]

Export:
[✓] Individual Frames
[✓] Sprite Sheet
[✓] Metadata JSON
[ ] Godot .tres

              [ RENDER SPRITE SHEET ]
```

---

## 3. Core Architecture

Recommended package layout:

```text
rastersheet/
│
├── __init__.py
├── operators.py
├── panel.py
├── properties.py
├── renderer.py
├── camera.py
├── lighting.py
├── spritesheet.py
├── metadata.py
└── utils.py
```

### Responsibilities

#### `__init__.py`

Registers classes, `PropertyGroup`, panels, and operators.

```python
bl_info = {
    "name": "RasterSheet",
    "author": "...",
    "version": (0, 1, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > RasterSheet",
    "category": "Render",
}
```

Targeting Blender 4.0+ is recommended unless older versions are specifically required.

---

## 4. Scene Safety

This is a core requirement.

The plugin should **not**:

```text
parent objects
change origins
apply transforms
delete user cameras
insert permanent keyframes
change object hierarchy
```

Instead, capture state before rendering and restore it afterward.

```python
original_matrix = obj.matrix_world.copy()
original_rotation_mode = obj.rotation_mode

try:
    render_frames(...)
finally:
    obj.matrix_world = original_matrix
    obj.rotation_mode = original_rotation_mode
```

Each sprite frame should be rendered explicitly rather than relying on Blender animation.

```python
for frame in range(frame_count):
    angle = frame / frame_count * rotation_amount

    obj.rotation_quaternion = (
        base_rotation
        @ Quaternion(local_axis, angle)
    )

    render_frame(frame)
```

Then restore the original state.

```python
obj.matrix_world = original_matrix
```

---

## 5. Rotation Engine

Support:

```text
Local X
Local Y
Local Z

World X
World Y
World Z
```

Default:

```text
Local Y
```

Axis mapping:

```python
axis_map = {
    "LOCAL_X": Vector((1, 0, 0)),
    "LOCAL_Y": Vector((0, 1, 0)),
    "LOCAL_Z": Vector((0, 0, 1)),
}
```

For local rotation:

```python
rotation = Quaternion(axis, angle)

obj.rotation_quaternion = (
    original_quaternion @ rotation
)
```

For world-axis rotation:

```python
obj.rotation_quaternion = (
    rotation @ original_quaternion
)
```

This distinction should be explicit in the UI.

---

## 6. Multiple-Object Support

V1 can operate on the active object.

Later support:

```text
Target Mode:

(•) Active Object
( ) Selected Objects
( ) Collection
```

For multi-object rendering, **do not parent them**.

Instead, determine a common pivot and mathematically rotate each object's world transform around that pivot.

```python
pivot = combined_bounds_center
```

Store original transforms first:

```python
original_matrices = {
    obj: obj.matrix_world.copy()
    for obj in objects
}
```

Then calculate temporary rotated transforms for each frame and restore all matrices afterward.

---

## 7. Camera Modes

### Mode A — Current Camera

Default mode.

```text
Use whatever the artist already positioned.
Do not modify it.
```

This should be the safest and most predictable workflow.

### Mode B — Auto Orthographic

Automatically create a temporary orthographic camera.

Algorithm:

1. Determine combined object bounds.
2. Determine desired view direction.
3. Create temporary orthographic camera.
4. Calculate aspect ratio:

```python
aspect = resolution_x / resolution_y
```

5. Determine maximum projected dimensions across all rotations.
6. Calculate:

```python
required_vertical = max(
    projected_height,
    projected_width / aspect
)
```

7. Apply margin:

```python
camera.data.ortho_scale = required_vertical * camera_margin
```

The projected bounds should be sampled across all sprite angles before rendering.

```python
for angle in angles:
    calculate_projected_bounds(angle)
```

No heuristic guessing.

---

## 8. Lighting Modes

Expose:

```text
Lighting:

Material Preview
Scene World
Scene Lights
Flat / Uniform
Custom HDRI
```

### Material Preview

Find Blender studio HDRIs with:

```python
bpy.utils.system_resource(
    'DATAFILES',
    path="studiolights/world"
)
```

Populate a dynamic enum with available HDRIs rather than choosing an arbitrary file.

Example choices:

```text
Forest
Interior
City
Night
Studio
...
```

### Scene World

Leave `scene.world` untouched.

### Custom HDRI

Example UI:

```text
HDRI:
[/home/user/foo.exr]

Strength:
[1.0]
```

---

## 9. Temporary Render State

Snapshot any render settings the plugin changes.

Example:

```python
state = {
    "engine": scene.render.engine,
    "res_x": scene.render.resolution_x,
    "res_y": scene.render.resolution_y,
    "film_transparent": scene.render.film_transparent,
    "filepath": scene.render.filepath,
}
```

Then:

```python
try:
    setup_render()
    render()
finally:
    restore_render_state(state)
```

Do the same for the World.

Prefer creating a temporary World:

```python
temp_world = bpy.data.worlds.new(...)
scene.world = temp_world
```

Then restore the original World afterward instead of modifying the user's World node tree.

---

## 10. Rendering Pipeline

Pseudo-code:

```python
def generate_sheet(context, settings):

    targets = resolve_targets(settings)

    snapshot = capture_scene_state(
        scene,
        targets
    )

    try:
        configure_renderer(settings)

        setup_camera(settings)

        setup_lighting(settings)

        for i in range(settings.frame_count):

            angle = calculate_angle(i)

            apply_temporary_rotation(
                targets,
                angle
            )

            context.view_layer.update()

            render_frame(
                output_path(i)
            )

        pack_frames()

        export_metadata()

    finally:
        restore_scene(snapshot)
```

The `finally` block is mandatory so a failed render does not leave the scene mutated.

---

## 11. Sprite-Sheet Packing

Can be implemented entirely with Blender's image API.

Input:

```text
frame_0001.png
frame_0002.png
...
```

Rows:

```python
rows = ceil(frame_count / columns)
```

Final resolution:

```python
sheet_width  = columns * frame_width
sheet_height = rows * frame_height
```

Example:

```text
16 frames
256×128
4 columns

= 1024×512
```

---

## 12. Sheet Layout Options

Support:

```text
Grid
Horizontal Strip
Vertical Strip
```

Grid:

```text
Columns: manually set
Rows: calculated
```

Horizontal:

```text
16 × 1
```

Vertical:

```text
1 × 16
```

---

## 13. Metadata Format

Generic JSON:

```json
{
  "image": "nuke_spin.png",
  "frame_count": 16,
  "columns": 4,
  "rows": 4,
  "frame_width": 256,
  "frame_height": 128,
  "fps": 12,
  "loop": true,
  "rotation": {
    "axis": "LOCAL_Y",
    "start_angle": 0,
    "rotation_amount": 360
  }
}
```

---

## 14. Godot Support

Optional export:

```text
[✓] Generate Godot SpriteFrames
```

Plugin outputs:

```text
nuke_spin.png
nuke_spin.tres
```

The `.tres` should define a `SpriteFrames` resource using `AtlasTexture` regions for each sprite frame.

Conceptual structure:

```text
[gd_resource type="SpriteFrames" load_steps=18 format=3]

[ext_resource type="Texture2D" path="res://nuke_spin.png" id="1"]
```

Each frame region:

```text
0,0,256,128
256,0,256,128
512,0,256,128
...
```

Godot usage:

```gdscript
$AnimatedSprite2D.sprite_frames = preload("res://nuke_spin.tres")
$AnimatedSprite2D.play("spin")
```

This removes the manual sprite-sheet slicing step.

---

## 15. Future Godot Integration

Eventually export a self-contained directory:

```text
nuke_spin/
├── nuke_spin.png
├── nuke_spin.tres
└── nuke_spin.json
```

Including animation metadata such as:

```text
Animation name: spin
FPS: 12
Loop: true
```

---

## 16. UI Property Definitions

Example:

```python
class RasterSheetSettings(bpy.types.PropertyGroup):

    frame_count: bpy.props.IntProperty(
        name="Frames",
        default=16,
        min=2,
        max=256,
    )

    columns: bpy.props.IntProperty(
        name="Columns",
        default=4,
        min=1,
        max=256,
    )

    rotation_axis: bpy.props.EnumProperty(
        name="Axis",
        items=[
            ("LOCAL_X", "Local X", ""),
            ("LOCAL_Y", "Local Y", ""),
            ("LOCAL_Z", "Local Z", ""),
            ("WORLD_X", "World X", ""),
            ("WORLD_Y", "World Y", ""),
            ("WORLD_Z", "World Z", ""),
        ],
        default="LOCAL_Y",
    )

    camera_mode: bpy.props.EnumProperty(
        name="Camera",
        items=[
            ("CURRENT", "Current Camera", ""),
            ("AUTO_ORTHO", "Auto Orthographic", ""),
        ],
        default="CURRENT",
    )

    transparent: bpy.props.BoolProperty(
        name="Transparent",
        default=True,
    )

    fps: bpy.props.FloatProperty(
        name="FPS",
        default=12.0,
        min=0.1,
    )
```

---

## 17. Blender Panel

Basic implementation:

```python
class RASTERSHEET_PT_panel(bpy.types.Panel):

    bl_label = "RasterSheet"
    bl_idname = "RASTERSHEET_PT_panel"

    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "RasterSheet"

    def draw(self, context):
        layout = self.layout

        settings = context.scene.rastersheet

        layout.prop(settings, "frame_count")
        layout.prop(settings, "rotation_axis")
        layout.prop(settings, "camera_mode")
        layout.prop(settings, "columns")
        layout.prop(settings, "fps")

        layout.operator(
            "rastersheet.render"
        )
```

---

## 18. Operator

```python
class RASTERSHEET_OT_render(
    bpy.types.Operator
):

    bl_idname = "rastersheet.render"
    bl_label = "Render Sprite Sheet"

    def execute(self, context):

        try:
            generate_sprite_sheet(context)

        except Exception as exc:

            self.report(
                {'ERROR'},
                str(exc)
            )

            return {'CANCELLED'}

        self.report(
            {'INFO'},
            "Sprite sheet generated"
        )

        return {'FINISHED'}
```

---

## 19. V1 Feature Set

Keep V1 focused:

- active object
- local X/Y/Z rotation
- current camera
- auto orthographic camera
- current scene resolution or custom resolution
- Eevee
- Material Preview HDRI
- transparent PNG
- arbitrary frame count
- grid sheet
- individual frame export
- JSON metadata
- Godot `.tres`
- full scene-state restoration

---

## 20. V2 Features

Potential additions:

```text
Selected object groups
Collections
World-axis rotation
Custom pivot
Custom HDRI
Perspective camera
Animation clips
Turntable elevation
Directional sprite generation
Automatic crop
Automatic padding
Normal/depth/emission passes
Godot export
Unity export
Aseprite JSON
```

---

## 21. Multiple Elevations / Impostor Generation

Extend RasterSheet into a general 3D → 2D impostor generator.

Example:

```text
Azimuth frames: 16
Elevation frames: 5
```

Render elevations:

```text
-60°
-30°
  0°
+30°
+60°
```

Each with 16 azimuth rotations:

```text
80 sprites
```

This creates a directional representation of the object across many viewing angles.

---

## 22. Render Passes

Optional game-shader outputs:

```text
spritesheet_color.png
spritesheet_normal.png
spritesheet_depth.png
spritesheet_emission.png
```

This allows runtime relighting of rasterized sprites in engines such as Godot.

---

## 23. Final Architecture

```text
             Blender Scene
                  │
                  ▼
          Target Resolver
                  │
                  ▼
        Transform Snapshot
                  │
        ┌─────────┴─────────┐
        ▼                   ▼
 Camera Controller     Lighting Controller
        │                   │
        └─────────┬─────────┘
                  ▼
          Frame Renderer
                  │
        ┌─────────┴──────────┐
        ▼                    ▼
    PNG Frames         Render Passes
        │
        ▼
    Sheet Packer
        │
    ┌───┴───────────────┐
    ▼                   ▼
 spritesheet.png      metadata
                         │
                    ┌────┴─────┐
                    ▼          ▼
                   JSON       Godot
                              .tres
```

The central principle is that RasterSheet acts like an **exporter**, not a modeling tool. It reads the scene, temporarily evaluates alternate orientations, renders them, and leaves the `.blend` exactly as it found it.
