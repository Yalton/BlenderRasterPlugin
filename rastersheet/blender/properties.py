"""The add-on's settings, stored on the scene."""

import os

import bpy

# Blender expects enum item strings to stay alive for as long as the enum is in
# use. Holding them in a module-level cache avoids the classic crash where the
# callback's temporaries are garbage collected mid-draw.
_STUDIO_LIGHT_CACHE = []


def _studio_light_items(self, context):
    _STUDIO_LIGHT_CACHE.clear()
    try:
        directory = bpy.utils.system_resource("DATAFILES", path="studiolights/world")
        names = sorted(n for n in os.listdir(directory) if n.lower().endswith(".exr"))
    except (OSError, TypeError):
        names = []

    if not names:
        _STUDIO_LIGHT_CACHE.append(("NONE", "None Found", "No studio HDRIs in this Blender build"))
        return _STUDIO_LIGHT_CACHE

    for name in names:
        label = os.path.splitext(name)[0].replace("_", " ").title()
        _STUDIO_LIGHT_CACHE.append((name, label, f"Studio HDRI {name}"))
    return _STUDIO_LIGHT_CACHE


class RasterSheetSettings(bpy.types.PropertyGroup):
    rotation_axis: bpy.props.EnumProperty(
        name="Axis",
        items=[
            ("LOCAL_X", "Local X", "Rotate about the object's own X axis"),
            ("LOCAL_Y", "Local Y", "Rotate about the object's own Y axis"),
            ("LOCAL_Z", "Local Z", "Rotate about the object's own Z axis"),
            ("WORLD_X", "World X", "Rotate about the world X axis"),
            ("WORLD_Y", "World Y", "Rotate about the world Y axis"),
            ("WORLD_Z", "World Z", "Rotate about the world Z axis"),
        ],
        default="LOCAL_Y",
    )
    frame_count: bpy.props.IntProperty(name="Frames", default=16, min=2, max=256)
    clockwise: bpy.props.BoolProperty(name="Clockwise", default=True)
    start_angle: bpy.props.FloatProperty(name="Start Angle", default=0.0, subtype="ANGLE")
    sweep_angle: bpy.props.FloatProperty(name="Rotation Amount", default=360.0)
    pivot_mode: bpy.props.EnumProperty(
        name="Pivot",
        items=[
            ("ORIGIN", "Object Origin", "Rotate about the object's origin"),
            ("BOUNDS_CENTER", "Bounds Center", "Rotate about the center of the evaluated bounds"),
        ],
        default="ORIGIN",
    )

    camera_mode: bpy.props.EnumProperty(
        name="Camera",
        items=[
            ("CURRENT", "Current Camera", "Use the scene camera, unmodified"),
            ("AUTO_ORTHO", "Auto Orthographic", "Build a temporary orthographic camera"),
        ],
        default="CURRENT",
    )
    azimuth: bpy.props.FloatProperty(name="Azimuth", default=0.0)
    elevation: bpy.props.FloatProperty(name="Elevation", default=30.0)
    camera_margin: bpy.props.FloatProperty(name="Margin", default=1.2, min=1.0)

    engine_mode: bpy.props.EnumProperty(
        name="Renderer",
        items=[
            ("SCENE", "Scene", "Leave the scene's render engine unchanged"),
            ("EEVEE", "Eevee", "Render with Eevee"),
            ("CYCLES", "Cycles", "Render with Cycles"),
        ],
        default="SCENE",
    )
    lighting_mode: bpy.props.EnumProperty(
        name="Lighting",
        items=[
            ("MATERIAL_PREVIEW", "Material Preview", "Light with a bundled studio HDRI"),
            ("SCENE_WORLD", "Scene World", "Leave the scene's world untouched"),
            ("SCENE_LIGHTS", "Scene Lights", "Black world, scene lamps only"),
            ("FLAT", "Flat / Uniform", "Even white ambient light (not unlit shading)"),
            ("CUSTOM_HDRI", "Custom HDRI", "Light with a user-supplied HDRI"),
        ],
        default="MATERIAL_PREVIEW",
    )
    studio_light: bpy.props.EnumProperty(name="Studio HDRI", items=_studio_light_items)
    hdri_path: bpy.props.StringProperty(name="HDRI", subtype="FILE_PATH", default="")
    hdri_strength: bpy.props.FloatProperty(name="Strength", default=1.0, min=0.0)

    # The view_transform enum cannot be introspected -- its enum_items report a
    # single NONE entry because the values come from the OCIO config at
    # runtime. These are a static list, and assignment is guarded.
    view_transform_mode: bpy.props.EnumProperty(
        name="View Transform",
        items=[
            ("STANDARD", "Standard", "Colors match the authored materials"),
            ("SCENE", "Scene", "Leave the scene's view transform unchanged"),
            ("AGX", "AgX", "Blender's default filmic transform"),
            ("FILMIC", "Filmic", "The legacy filmic transform"),
        ],
        default="STANDARD",
    )
    transparent: bpy.props.BoolProperty(name="Transparent BG", default=True)

    resolution_mode: bpy.props.EnumProperty(
        name="Resolution",
        items=[
            ("SCENE", "Scene Resolution", "Use the scene's render resolution"),
            ("CUSTOM", "Custom", "Use the width and height below"),
        ],
        default="SCENE",
    )
    resolution_x: bpy.props.IntProperty(name="Width", default=256, min=1)
    resolution_y: bpy.props.IntProperty(name="Height", default=256, min=1)

    sheet_mode: bpy.props.EnumProperty(
        name="Layout",
        items=[
            ("GRID", "Grid", "Rows and columns"),
            ("HORIZONTAL", "Horizontal Strip", "One row"),
            ("VERTICAL", "Vertical Strip", "One column"),
        ],
        default="GRID",
    )
    columns: bpy.props.IntProperty(name="Columns", default=4, min=1, max=256)

    output_dir: bpy.props.StringProperty(
        name="Output Directory", subtype="DIR_PATH", default="//sprite_output/"
    )
    filename_stem: bpy.props.StringProperty(name="Filename", default="sprite")

    export_frames: bpy.props.BoolProperty(name="Individual Frames", default=True)
    export_sheet: bpy.props.BoolProperty(name="Sprite Sheet", default=True)
    export_json: bpy.props.BoolProperty(name="Metadata JSON", default=True)
    export_godot: bpy.props.BoolProperty(name="Godot .tres", default=False)
    godot_res_prefix: bpy.props.StringProperty(name="Godot Prefix", default="res://")

    animation_name: bpy.props.StringProperty(name="Animation", default="spin")
    fps: bpy.props.FloatProperty(name="FPS", default=12.0, min=0.1)
    loop: bpy.props.BoolProperty(name="Loop", default=True)
