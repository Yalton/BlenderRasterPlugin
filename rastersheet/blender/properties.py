"""The add-on's settings, stored on the scene."""

import math
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
    frame_count: bpy.props.IntProperty(name="Frames", default=16, min=1, max=256)
    clockwise: bpy.props.BoolProperty(name="Clockwise", default=True)
    start_angle: bpy.props.FloatProperty(name="Start Angle", default=0.0, subtype="ANGLE")
    sweep_angle: bpy.props.FloatProperty(
        name="Rotation Amount", default=math.radians(360.0), subtype="ANGLE"
    )
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

    # Stylize: every effect is off by default, so a render with none ticked
    # is byte-for-byte the plain render.
    stylize_toon: bpy.props.BoolProperty(
        name="Toon Shading",
        default=False,
        description="Flatten lighting into hard bands (Eevee only). Renders with copies of the materials",
    )
    toon_bands: bpy.props.IntProperty(name="Bands", default=3, min=2, max=8)
    toon_matte: bpy.props.BoolProperty(
        name="Matte",
        default=False,
        description=(
            "Render metallic materials as non-metallic so light shades their form. "
            "Metal under a single lamp is black apart from its highlight"
        ),
    )
    toon_smooth: bpy.props.BoolProperty(
        name="Ignore Surface Detail",
        default=False,
        description=(
            "Disconnect normal, displacement and roughness maps so bands follow the "
            "model's shape instead of breaking into speckle along their edges"
        ),
    )
    toon_flat_color: bpy.props.BoolProperty(
        name="Flat Color",
        default=False,
        description=(
            "Replace each color texture with its average color, so every part is one "
            "flat fill instead of banded photographic grime"
        ),
    )
    toon_faceted: bpy.props.BoolProperty(
        name="Faceted",
        default=False,
        description="Shade by true face normals: bands become crisp planes instead of soft blobs",
    )
    toon_rim: bpy.props.BoolProperty(
        name="Rim Light",
        default=False,
        description="A hard band of color where surfaces turn away from the camera",
    )
    toon_rim_color: bpy.props.FloatVectorProperty(
        name="Rim Color", subtype="COLOR", size=3, min=0.0, soft_max=1.0, default=(0.3, 0.9, 1.0)
    )
    toon_rim_width: bpy.props.FloatProperty(
        name="Rim Width", default=0.3, min=0.0, max=1.0, subtype="FACTOR"
    )
    toon_brightness: bpy.props.FloatProperty(
        name="Brightness",
        default=1.0,
        min=0.0,
        soft_max=2.0,
        subtype="FACTOR",
        description="Scale every band's on-screen brightness; below 1 darkens toward a moodier look",
    )
    toon_saturation: bpy.props.FloatProperty(
        name="Saturation",
        default=1.0,
        min=0.0,
        soft_max=2.0,
        subtype="FACTOR",
        description="Scale color intensity; above 1 pushes toward flat comic color",
    )
    toon_ink_shadows: bpy.props.FloatProperty(
        name="Ink Shadows",
        default=0.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        description="Bands at or below this brightness become solid black, like inked comic shadows",
    )
    stylize_outline_3d: bpy.props.BoolProperty(
        name="Ink Outline (3D)",
        default=False,
        description="Inverted-hull ink lines around meshes, including where parts overlap",
    )
    outline_3d_width: bpy.props.FloatProperty(
        name="Line Width", default=0.02, min=0.0, soft_max=0.5, subtype="DISTANCE"
    )
    stylize_silhouette: bpy.props.BoolProperty(
        name="Silhouette Outline (2D)",
        default=False,
        description="Solid ink band around the rendered shape's outer edge, in pixels",
    )
    silhouette_width: bpy.props.IntProperty(name="Width (px)", default=3, min=1, max=64)
    ink_color: bpy.props.FloatVectorProperty(
        name="Ink Color",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(0.0, 0.0, 0.0, 1.0),
    )
    stylize_glow: bpy.props.BoolProperty(
        name="Glow",
        default=False,
        description="Bloom halo around bright and emissive pixels, spilling onto the background",
    )
    glow_threshold: bpy.props.FloatProperty(
        name="Threshold", default=0.75, min=0.0, max=0.99, subtype="FACTOR"
    )
    glow_radius: bpy.props.IntProperty(name="Radius (px)", default=12, min=1, max=256)
    glow_intensity: bpy.props.FloatProperty(name="Intensity", default=1.0, min=0.0, soft_max=4.0)
    stylize_posterize: bpy.props.BoolProperty(
        name="Posterize",
        default=False,
        description="Reduce each color channel to a few flat levels",
    )
    posterize_levels: bpy.props.IntProperty(name="Levels", default=6, min=2, max=32)
    stylize_pixelate: bpy.props.BoolProperty(
        name="Pixelate",
        default=False,
        description="Chunky pixels at the same frame size",
    )
    pixel_size: bpy.props.IntProperty(name="Pixel Size", default=4, min=2, max=64)
    pixel_hard_alpha: bpy.props.BoolProperty(name="Hard Edges", default=True)

    animation_name: bpy.props.StringProperty(name="Animation", default="spin")
    fps: bpy.props.FloatProperty(name="FPS", default=12.0, min=0.1)
    loop: bpy.props.BoolProperty(name="Loop", default=True)
