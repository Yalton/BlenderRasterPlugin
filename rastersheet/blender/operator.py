"""The render operator: validation, orchestration, restoration."""

import math
import os
import shutil
import tempfile

import bpy
from mathutils import Vector

from ..core.angles import frame_angles
from ..core.godot import sprite_frames_tres
from ..core.layout import sheet_layout
from ..core.metadata import build_metadata
from ..core.paths import build_output_paths, frame_filename
from ..core.rotation import axis_vector, frame_matrix
from . import camera as camera_module
from . import export as export_module
from . import lighting as lighting_module
from . import packing as packing_module
from . import render as render_module
from . import snapshot

MAX_SHEET_SIDE = 16384

# Eevee's enum identifier changed mid-range: BLENDER_EEVEE_NEXT in 4.2/4.3,
# BLENDER_EEVEE from 4.5 on.
EEVEE_RENAMED_IN = (4, 5, 0)

VIEW_TRANSFORMS = {
    "STANDARD": "Standard",
    "AGX": "AgX",
    "FILMIC": "Filmic",
}


def registered_engine_ids():
    """Every engine identifier registered in the *running* build.

    `scene.render.bl_rna.properties["engine"].enum_items` cannot answer this:
    it returns the static RNA stub declared at compile time, which on 5.2
    lists only BLENDER_EEVEE -- Workbench is missing from it too, and
    Workbench ships in every build. Assigning "CYCLES" or "BLENDER_WORKBENCH"
    to that same property succeeds regardless, so the stub is not a statement
    about availability.

    The registration table itself is the truth: engines implemented in Python
    (Cycles among them) register as subclasses of bpy.types.RenderEngine.
    Some subclasses -- HydraRenderEngine is the one in this build -- are
    abstract bases with no bl_idname, so read it defensively and recurse,
    because a concrete engine can sit under an intermediate base.
    """
    found = set()

    def walk(cls):
        for subclass in cls.__subclasses__():
            identifier = getattr(subclass, "bl_idname", None)
            if identifier:
                found.add(identifier)
            walk(subclass)

    walk(bpy.types.RenderEngine)
    return found


def resolve_engine(scene, mode):
    """Map the add-on's engine choice onto this build's engine identifier.

    `scene` is unused but kept in the signature: every call site passes it,
    and a future build could make availability scene-dependent.

    Both branches read the running build, never a compile-time constant.
    Eevee is built in and always present, so only its *name* is in question
    and `bpy.app.version` settles it. Cycles genuinely can be absent (it is a
    Python-registered engine and can be disabled), so it is looked up in the
    live registration table.
    """
    if mode == "EEVEE":
        return "BLENDER_EEVEE" if bpy.app.version >= EEVEE_RENAMED_IN else "BLENDER_EEVEE_NEXT"
    if mode == "CYCLES":
        if "CYCLES" in registered_engine_ids():
            return "CYCLES"
        raise RuntimeError("Cycles is not available in this Blender build")
    raise RuntimeError(f"Unknown engine mode {mode!r}")


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


def resolved_output_dir(settings):
    """The absolute filesystem path `settings.output_dir` names.

    `core.paths` documents that `output_dir` must already be absolute when it
    arrives, and this is the boundary that has to honour that. `bpy.path.abspath`
    only expands the `//` prefix, and when the .blend has never been saved it
    cannot expand it at all -- it hands back a *relative* string. os.path.abspath
    finishes the job so everything downstream sees one real path.
    """
    return os.path.abspath(bpy.path.abspath(settings.output_dir))


def _creation_blocker(path):
    """Walk up to the nearest existing directory, reporting what blocks creation.

    Returns `(ancestor, blocker)`: `ancestor` is the nearest existing directory
    at or above `path`, and `blocker` is an existing *non*-directory component
    on the way up, if any -- `os.makedirs` will fail on that later in `run()`,
    so validation says so up front instead.

    `path` must be absolute. A relative path bottoms this walk out at `""`,
    and `os.access("", os.W_OK)` is False, which is how the default
    `//sprite_output/` used to fail validation on an unsaved .blend.

    Answers "could I create this directory?" without actually creating
    anything -- validation must never mutate the filesystem, only `run()` is
    allowed to.
    """
    current = os.path.abspath(path)
    blocker = None
    while not os.path.isdir(current):
        if os.path.exists(current):
            # A regular file (or anything else that is not a directory) sitting
            # where a path component has to be. The highest such component is
            # the one that actually stops makedirs, so keep overwriting.
            blocker = current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return current, blocker


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

    if settings.export_godot and not settings.export_sheet:
        problems.append("Godot export needs the sprite sheet enabled")

    if settings.export_godot and not settings.godot_res_prefix.strip():
        problems.append("Godot export needs a non-empty resource path prefix")

    if scene.render.pixel_aspect_x != 1.0 or scene.render.pixel_aspect_y != 1.0:
        problems.append("Non-square pixel aspect ratios are not supported")

    if settings.engine_mode != "SCENE":
        try:
            resolve_engine(scene, settings.engine_mode)
        except RuntimeError as exc:
            problems.append(str(exc))

    if settings.lighting_mode == "CUSTOM_HDRI":
        path = bpy.path.abspath(settings.hdri_path)
        if not path or not os.path.isfile(path):
            problems.append("Custom HDRI mode needs a readable image path")

    width, height = resolution_for(scene, settings)
    if settings.frame_count >= 2:
        layout = sheet_layout(settings.frame_count, settings.columns, settings.sheet_mode, width, height)
        if layout.sheet_width > MAX_SHEET_SIDE or layout.sheet_height > MAX_SHEET_SIDE:
            problems.append(
                f"Sheet would be {layout.sheet_width}x{layout.sheet_height}, "
                f"over Blender's {MAX_SHEET_SIDE}px limit"
            )

    if not bpy.data.filepath and settings.output_dir.startswith("//"):
        # `//` means "relative to the .blend", and there is no .blend yet, so
        # there is no directory to talk about -- including for the property's
        # own default of `//sprite_output/`. Say what to do about it rather
        # than reporting the unexpanded string as unwritable.
        problems.append(
            "Output directory is relative to the .blend file, which has not been "
            "saved yet: save the .blend first, or set an absolute output directory"
        )
    else:
        output_dir = resolved_output_dir(settings)
        ancestor, blocker = _creation_blocker(output_dir)
        if blocker is not None:
            problems.append(
                f"Output directory cannot be created: {blocker} is a file, not a directory"
            )
        elif not os.access(ancestor, os.W_OK):
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

        output_dir = resolved_output_dir(settings)
        paths = build_output_paths(output_dir, settings.filename_stem)
        # Created unconditionally: the sheet, JSON, and .tres can each be
        # written independently of whether individual frames are kept, so
        # output_dir must exist even when export_frames (the only other
        # thing that used to create it, as a side effect of making
        # frames_dir inside it) is off.
        os.makedirs(output_dir, exist_ok=True)

        temp_frames_dir = None
        if settings.export_frames:
            frames_dir = paths.frames_dir
            os.makedirs(frames_dir, exist_ok=True)
        else:
            temp_frames_dir = tempfile.mkdtemp(prefix="rastersheet_")
            frames_dir = temp_frames_dir

        width, height = resolution_for(scene, settings)

        try:
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
                frame_matrices = [
                    frame_matrix(base_matrix, axis, angle, pivot) for angle in angles
                ]

                scene.render.resolution_x = width
                scene.render.resolution_y = height
                scene.render.resolution_percentage = 100
                scene.render.film_transparent = settings.transparent
                scene.render.image_settings.file_format = "PNG"
                scene.render.image_settings.color_mode = "RGBA" if settings.transparent else "RGB"
                scene.render.image_settings.color_depth = "8"

                if settings.engine_mode != "SCENE":
                    scene.render.engine = resolve_engine(scene, settings.engine_mode)

                if settings.view_transform_mode != "SCENE":
                    name = VIEW_TRANSFORMS[settings.view_transform_mode]
                    try:
                        scene.view_settings.view_transform = name
                    except TypeError:
                        self.report(
                            {"WARNING"},
                            f"View transform {name!r} is unavailable; keeping the scene's",
                        )

                lighting_module.apply_lighting(context, settings, stack)

                corners = local_corners(obj, depsgraph)
                scene.camera = camera_module.resolve_camera(
                    context, settings, stack, obj, corners, frame_matrices, width / height
                )

                window_manager.progress_begin(0, settings.frame_count)
                try:
                    jobs = render_module.frame_jobs(
                        context, scene, obj, frame_matrices, frames_dir, paths.stem
                    )
                    for index in jobs:
                        window_manager.progress_update(index + 1)
                finally:
                    window_manager.progress_end()

            layout = sheet_layout(
                settings.frame_count,
                settings.columns,
                settings.sheet_mode,
                width,
                height,
            )

            if settings.export_sheet:
                frame_paths = [
                    os.path.join(frames_dir, frame_filename(paths.stem, index))
                    for index in range(settings.frame_count)
                ]
                packing_module.pack_sheet(frame_paths, layout, paths.sheet)

            image_name = os.path.basename(paths.sheet)

            if settings.export_json:
                document = build_metadata(
                    image_name=image_name,
                    layout=layout,
                    animation_name=settings.animation_name,
                    fps=settings.fps,
                    loop=settings.loop,
                    axis=settings.rotation_axis,
                    start_deg=math.degrees(settings.start_angle),
                    sweep_deg=math.degrees(settings.sweep_angle),
                    clockwise=settings.clockwise,
                )
                export_module.write_metadata(paths.json, document)

            if settings.export_godot:
                # validate() tests `godot_res_prefix.strip()`, so a
                # whitespace-padded prefix is accepted; strip it here too or
                # the accepted value and the used value differ and "  res://x  "
                # bakes its padding into the resource path.
                prefix = settings.godot_res_prefix.strip()
                if prefix and not prefix.endswith("/"):
                    prefix += "/"
                text = sprite_frames_tres(
                    f"{prefix}{image_name}",
                    layout,
                    settings.animation_name,
                    settings.fps,
                    settings.loop,
                )
                export_module.write_tres(paths.tres, text)
        finally:
            if temp_frames_dir is not None:
                shutil.rmtree(temp_frames_dir, ignore_errors=True)

        return paths
