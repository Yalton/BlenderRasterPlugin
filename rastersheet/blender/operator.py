"""The render operator: validation, orchestration, restoration."""

import math
import os

import bpy
from mathutils import Vector

from ..core.angles import frame_angles
from ..core.paths import build_output_paths
from ..core.rotation import axis_vector, frame_matrix
from . import camera as camera_module
from . import render as render_module
from . import snapshot

MAX_SHEET_SIDE = 16384


def local_corners(obj, depsgraph):
    """The eight bounding-box corners in the evaluated object's local space."""
    evaluated = obj.evaluated_get(depsgraph)
    return [Vector(corner) for corner in evaluated.bound_box]


def bounds_center(obj, depsgraph):
    corners = local_corners(obj, depsgraph)
    local_center = sum(corners, Vector((0.0, 0.0, 0.0))) / len(corners)
    return obj.matrix_world @ local_center


def resolution_for(scene, settings):
    if settings.resolution_mode == "CUSTOM":
        return settings.resolution_x, settings.resolution_y
    percent = scene.render.resolution_percentage / 100.0
    return (
        max(1, int(scene.render.resolution_x * percent)),
        max(1, int(scene.render.resolution_y * percent)),
    )


def validate(context, settings):
    """Return a list of blocking problems. An empty list means go."""
    problems = []
    scene = context.scene
    obj = context.active_object

    if obj is None:
        problems.append("No active object")
    elif obj.type not in {"MESH", "CURVE", "SURFACE", "META", "FONT"}:
        problems.append(f"Active object {obj.name!r} has no renderable geometry")

    if settings.camera_mode == "CURRENT" and scene.camera is None:
        problems.append("Camera mode is Current Camera but the scene has no camera")

    if settings.frame_count < 2:
        problems.append("Frame count must be at least 2")

    if scene.render.pixel_aspect_x != 1.0 or scene.render.pixel_aspect_y != 1.0:
        problems.append("Non-square pixel aspect ratios are not supported")

    if settings.engine_mode != "SCENE":
        available = {item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items}
        wanted = {"EEVEE": {"BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"}, "CYCLES": {"CYCLES"}}[settings.engine_mode]
        if not (available & wanted):
            problems.append(f"{settings.engine_mode.title()} is not available in this Blender build")

    if settings.lighting_mode == "CUSTOM_HDRI":
        path = bpy.path.abspath(settings.hdri_path)
        if not path or not os.path.isfile(path):
            problems.append("Custom HDRI mode needs a readable image path")

    width, height = resolution_for(scene, settings)
    columns = settings.frame_count if settings.sheet_mode == "HORIZONTAL" else (
        1 if settings.sheet_mode == "VERTICAL" else min(settings.columns, settings.frame_count)
    )
    rows = math.ceil(settings.frame_count / columns)
    if columns * width > MAX_SHEET_SIDE or rows * height > MAX_SHEET_SIDE:
        problems.append(
            f"Sheet would be {columns * width}x{rows * height}, over Blender's {MAX_SHEET_SIDE}px limit"
        )

    output_dir = bpy.path.abspath(settings.output_dir)
    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as exc:
        problems.append(f"Cannot create output directory: {exc}")
    else:
        if not os.access(output_dir, os.W_OK):
            problems.append(f"Output directory is not writable: {output_dir}")

    return problems


def warnings_for(context):
    obj = context.active_object
    if obj is not None and (obj.constraints or (obj.animation_data and obj.animation_data.drivers)):
        return [
            f"{obj.name!r} has constraints or drivers; its world matrix is recomputed "
            "during evaluation, so the rotation will not apply"
        ]
    return []


class RASTERSHEET_OT_render(bpy.types.Operator):
    bl_idname = "rastersheet.render"
    bl_label = "Render Sprite Sheet"
    bl_description = "Rotate the active object and render each angle to a sprite sheet"

    def execute(self, context):
        settings = context.scene.rastersheet

        problems = validate(context, settings)
        if problems:
            self.report({"ERROR"}, "; ".join(problems))
            return {"CANCELLED"}

        for warning in warnings_for(context):
            self.report({"WARNING"}, warning)

        try:
            self.run(context, settings)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, scene already restored
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        self.report({"INFO"}, "Sprite sheet generated")
        return {"FINISHED"}

    def run(self, context, settings):
        scene = context.scene
        obj = context.active_object
        window_manager = context.window_manager

        output_dir = bpy.path.abspath(settings.output_dir)
        paths = build_output_paths(output_dir, settings.filename_stem)
        frames_dir = paths.frames_dir
        os.makedirs(frames_dir, exist_ok=True)

        with snapshot.scene_snapshot(scene, [obj]) as stack:
            depsgraph = context.evaluated_depsgraph_get()
            base_matrix = obj.matrix_world.copy()
            pivot = (
                bounds_center(obj, depsgraph)
                if settings.pivot_mode == "BOUNDS_CENTER"
                else base_matrix.to_translation()
            )
            axis = axis_vector(settings.rotation_axis, base_matrix)
            angles = frame_angles(
                settings.frame_count,
                math.degrees(settings.start_angle),
                math.degrees(settings.sweep_angle),
                settings.clockwise,
            )
            frame_matrices = [frame_matrix(base_matrix, axis, angle, pivot) for angle in angles]

            width, height = resolution_for(scene, settings)
            scene.render.resolution_x = width
            scene.render.resolution_y = height
            scene.render.resolution_percentage = 100
            scene.render.film_transparent = settings.transparent
            scene.render.image_settings.file_format = "PNG"
            scene.render.image_settings.color_mode = "RGBA" if settings.transparent else "RGB"
            scene.render.image_settings.color_depth = "8"

            scene.camera = camera_module.resolve_camera(context, settings, stack, obj)

            window_manager.progress_begin(0, settings.frame_count)
            try:
                jobs = render_module.frame_jobs(
                    context, scene, obj, frame_matrices, frames_dir, paths.stem
                )
                for index in jobs:
                    window_manager.progress_update(index + 1)
            finally:
                window_manager.progress_end()

        return paths
