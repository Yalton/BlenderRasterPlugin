"""Headless Blender smoke tests. Run with: blender -b -P tests_blender/run_smoke.py"""

import math
import os
import sys
import traceback

import bpy
import mathutils

MODULE = "bl_ext.user_default.rastersheet"

SCRATCH = os.environ.get(
    "RASTERSHEET_SCRATCH",
    "/tmp/claude-1000/-data-fast-Projects-Tech-Tools-BlenderRasterPlugin/9802a33f-d74c-460a-b8f6-1fa7cd9626fc/scratchpad",
)


def _fresh_cube(name="RasterSheetProbe"):
    existing = bpy.data.objects.get(name)
    if existing:
        bpy.data.objects.remove(existing, do_unlink=True)
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    import bmesh

    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def enable_addon():
    bpy.ops.preferences.addon_enable(module=MODULE)


CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


@check
def test_addon_enables():
    assert MODULE in bpy.context.preferences.addons


@check
def test_settings_are_attached_to_the_scene():
    settings = bpy.context.scene.rastersheet
    assert settings is not None


@check
def test_every_property_round_trips():
    settings = bpy.context.scene.rastersheet
    settings.frame_count = 8
    settings.columns = 3
    settings.rotation_axis = "WORLD_Z"
    settings.camera_mode = "AUTO_ORTHO"
    settings.sheet_mode = "VERTICAL"
    settings.lighting_mode = "FLAT"
    settings.view_transform_mode = "AGX"
    settings.engine_mode = "EEVEE"
    settings.pivot_mode = "BOUNDS_CENTER"
    settings.filename_stem = "probe"
    settings.fps = 24.0
    assert settings.frame_count == 8
    assert settings.rotation_axis == "WORLD_Z"
    assert settings.view_transform_mode == "AGX"
    assert settings.filename_stem == "probe"
    assert abs(settings.fps - 24.0) < 1e-6


@check
def test_panel_is_registered():
    assert hasattr(bpy.types, "RASTERSHEET_PT_panel")


@check
def test_studio_light_enum_is_populated():
    # bl_rna.properties[...].enum_items only reflects Blender's own C-level
    # dynamic enums (and even those just report a NONE placeholder -- see
    # view_transform_mode's docstring in properties.py). For a Python itemsf
    # callback like studio_light, Blender calls the function when the
    # property is read, filling the module-level cache the callback
    # populates; that cache is what we can actually assert against here.
    settings = bpy.context.scene.rastersheet
    _ = settings.studio_light
    from bl_ext.user_default.rastersheet.blender.properties import _STUDIO_LIGHT_CACHE

    assert len(_STUDIO_LIGHT_CACHE) >= 1


@check
def test_snapshot_restores_scalars_and_matrices():
    from bl_ext.user_default.rastersheet.blender import snapshot

    scene = bpy.context.scene
    obj = _fresh_cube()
    before_engine = scene.render.engine
    before_res = scene.render.resolution_x
    before_matrix = obj.matrix_world.copy()

    with snapshot.scene_snapshot(scene, [obj]) as stack:
        snapshot.guard(stack, scene.render, "resolution_x")
        scene.render.resolution_x = 999
        obj.matrix_world = obj.matrix_world @ mathutils.Matrix.Translation((10.0, 0.0, 0.0))
        assert scene.render.resolution_x == 999

    assert scene.render.engine == before_engine
    assert scene.render.resolution_x == before_res
    assert (obj.matrix_world.to_translation() - before_matrix.to_translation()).length < 1e-6


@check
def test_snapshot_restores_after_a_failure():
    from bl_ext.user_default.rastersheet.blender import snapshot

    scene = bpy.context.scene
    obj = _fresh_cube()
    before = scene.render.resolution_x

    try:
        with snapshot.scene_snapshot(scene, [obj]) as stack:
            snapshot.guard(stack, scene.render, "resolution_x")
            scene.render.resolution_x = 777
            raise RuntimeError("deliberate failure")
    except RuntimeError:
        pass

    assert scene.render.resolution_x == before


@check
def test_snapshot_removes_tracked_datablocks():
    from bl_ext.user_default.rastersheet.blender import snapshot

    scene = bpy.context.scene
    before = len(bpy.data.worlds)
    before_world = scene.world

    with snapshot.scene_snapshot(scene, []) as stack:
        world = bpy.data.worlds.new("rastersheet_temp")
        snapshot.track_datablock(stack, bpy.data.worlds, world)
        scene.world = world
        assert len(bpy.data.worlds) == before + 1
        assert scene.world == world

    assert len(bpy.data.worlds) == before
    assert scene.world == before_world


@check
def test_snapshot_restores_image_settings_despite_order_dependency():
    # Regression test for the ordering bug found in review: file_format
    # governs which color_depth values are legal. If color_depth is
    # restored while file_format is still OPEN_EXR, setting a PNG-only
    # depth like '8' raises TypeError and is never restored. This test
    # deliberately drives that exact combination.
    from bl_ext.user_default.rastersheet.blender import snapshot

    scene = bpy.context.scene
    image_settings = scene.render.image_settings
    before_format = image_settings.file_format
    before_depth = image_settings.color_depth

    with snapshot.scene_snapshot(scene, []) as stack:
        image_settings.file_format = "OPEN_EXR"
        image_settings.color_depth = "32"
        assert image_settings.file_format == "OPEN_EXR"
        assert image_settings.color_depth == "32"

    assert image_settings.file_format == before_format
    assert image_settings.color_depth == before_depth


@check
def test_snapshot_restores_view_settings():
    from bl_ext.user_default.rastersheet.blender import snapshot

    scene = bpy.context.scene
    view_settings = scene.view_settings
    before_transform = view_settings.view_transform
    before_look = view_settings.look
    before_exposure = view_settings.exposure

    with snapshot.scene_snapshot(scene, []) as stack:
        view_settings.view_transform = "Standard"
        view_settings.exposure = 2.5
        assert view_settings.view_transform == "Standard"
        assert abs(view_settings.exposure - 2.5) < 1e-6

    assert view_settings.view_transform == before_transform
    assert view_settings.look == before_look
    assert abs(view_settings.exposure - before_exposure) < 1e-6


@check
def test_snapshot_restores_camera():
    from bl_ext.user_default.rastersheet.blender import snapshot

    scene = bpy.context.scene
    before_camera = scene.camera

    with snapshot.scene_snapshot(scene, []) as stack:
        temp_cam_data = bpy.data.cameras.new("RasterSheetTempCam")
        snapshot.track_datablock(stack, bpy.data.cameras, temp_cam_data)
        temp_cam_obj = bpy.data.objects.new("RasterSheetTempCamObj", temp_cam_data)
        scene.collection.objects.link(temp_cam_obj)
        snapshot.track_datablock(stack, bpy.data.objects, temp_cam_obj)
        scene.camera = temp_cam_obj
        assert scene.camera == temp_cam_obj

    assert scene.camera == before_camera


@check
def test_snapshot_restores_multiple_objects_independently():
    from bl_ext.user_default.rastersheet.blender import snapshot

    obj_a = _fresh_cube("RasterSheetProbeA")
    obj_b = _fresh_cube("RasterSheetProbeB")
    obj_a.matrix_world = mathutils.Matrix.Translation((1.0, 0.0, 0.0))
    obj_b.matrix_world = mathutils.Matrix.Translation((0.0, 2.0, 0.0))
    before_a = obj_a.matrix_world.copy()
    before_b = obj_b.matrix_world.copy()

    with snapshot.scene_snapshot(bpy.context.scene, [obj_a, obj_b]) as stack:
        obj_a.matrix_world = obj_a.matrix_world @ mathutils.Matrix.Translation((5.0, 0.0, 0.0))
        obj_b.matrix_world = obj_b.matrix_world @ mathutils.Matrix.Translation((0.0, 5.0, 0.0))
        assert (obj_a.matrix_world.to_translation() - before_a.to_translation()).length > 1.0
        assert (obj_b.matrix_world.to_translation() - before_b.to_translation()).length > 1.0

    assert (obj_a.matrix_world.to_translation() - before_a.to_translation()).length < 1e-6
    assert (obj_b.matrix_world.to_translation() - before_b.to_translation()).length < 1e-6


@check
def test_render_writes_individual_frames_and_restores_the_scene():
    import os
    import shutil

    scene = bpy.context.scene
    obj = _fresh_cube()
    bpy.context.view_layer.objects.active = obj

    camera_data = bpy.data.cameras.new("ProbeCam")
    camera = bpy.data.objects.new("ProbeCam", camera_data)
    scene.collection.objects.link(camera)
    camera.location = (0.0, -5.0, 0.0)
    camera.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    scene.camera = camera

    out = os.path.join(SCRATCH, "frames_run")
    shutil.rmtree(out, ignore_errors=True)

    settings = scene.rastersheet
    settings.frame_count = 4
    settings.resolution_mode = "CUSTOM"
    settings.resolution_x = 32
    settings.resolution_y = 32
    settings.output_dir = out
    settings.filename_stem = "probe"
    settings.export_frames = True
    settings.export_sheet = False
    settings.export_json = False
    settings.export_godot = False
    settings.camera_mode = "CURRENT"

    before_matrix = obj.matrix_world.copy()
    before_engine = scene.render.engine
    before_res_x = scene.render.resolution_x
    before_res_y = scene.render.resolution_y
    before_film_transparent = scene.render.film_transparent
    before_filepath = scene.render.filepath
    before_transform = scene.view_settings.view_transform

    result = bpy.ops.rastersheet.render()
    assert result == {"FINISHED"}, result

    frames = sorted(os.listdir(os.path.join(out, "probe_frames")))
    assert frames == ["probe_0001.png", "probe_0002.png", "probe_0003.png", "probe_0004.png"], frames

    assert (obj.matrix_world.to_translation() - before_matrix.to_translation()).length < 1e-6
    assert scene.render.engine == before_engine
    assert scene.render.resolution_x == before_res_x
    assert scene.render.resolution_y == before_res_y
    assert scene.render.film_transparent == before_film_transparent
    assert scene.render.filepath == before_filepath
    assert scene.view_settings.view_transform == before_transform


@check
def test_render_rejects_a_missing_camera_without_touching_the_scene():
    scene = bpy.context.scene
    obj = _fresh_cube()
    bpy.context.view_layer.objects.active = obj
    previous_camera = scene.camera
    scene.camera = None
    before_filepath = scene.render.filepath

    scene.rastersheet.camera_mode = "CURRENT"
    # An ERROR-level self.report() combined with returning {'CANCELLED'} is
    # raised by Blender as a RuntimeError when the operator is invoked via
    # bpy.ops from a script, rather than returned as {'CANCELLED'} -- this is
    # standard Blender behavior (verified against this build), not a bug in
    # the operator.
    try:
        result = bpy.ops.rastersheet.render()
    except RuntimeError as exc:
        assert "camera" in str(exc).lower(), exc
    else:
        raise AssertionError(f"expected a RuntimeError, got {result}")

    assert scene.render.filepath == before_filepath
    scene.camera = previous_camera


@check
def test_render_restores_the_scene_when_a_frame_fails_mid_loop():
    import os
    import shutil

    # Provoke a genuine, organic failure partway through the frame loop --
    # not a monkeypatch -- by pre-creating the *second* frame's output path
    # as a directory. Frame 1 renders and writes normally; frame 2's
    # write_still then fails for real inside bpy.ops.render.render because
    # it cannot save a PNG where a directory already sits. This exercises
    # the actual per-operator unwind path (RASTERSHEET_OT_render.run's
    # scene_snapshot), not just scene_snapshot's own generic exception
    # handling, which Task 6 already covers.
    scene = bpy.context.scene
    obj = _fresh_cube()
    bpy.context.view_layer.objects.active = obj

    camera_data = bpy.data.cameras.new("ProbeCamFail")
    camera = bpy.data.objects.new("ProbeCamFail", camera_data)
    scene.collection.objects.link(camera)
    camera.location = (0.0, -5.0, 0.0)
    camera.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    scene.camera = camera

    out = os.path.join(SCRATCH, "frames_fail_run")
    shutil.rmtree(out, ignore_errors=True)
    frames_dir = os.path.join(out, "probe_frames")
    os.makedirs(frames_dir)
    os.makedirs(os.path.join(frames_dir, "probe_0002.png"))

    settings = scene.rastersheet
    settings.frame_count = 4
    settings.resolution_mode = "CUSTOM"
    settings.resolution_x = 32
    settings.resolution_y = 32
    settings.output_dir = out
    settings.filename_stem = "probe"
    settings.export_frames = True
    settings.export_sheet = False
    settings.export_json = False
    settings.export_godot = False
    settings.camera_mode = "CURRENT"

    before_matrix = obj.matrix_world.copy()
    before_engine = scene.render.engine
    before_res_x = scene.render.resolution_x
    before_res_y = scene.render.resolution_y
    before_film_transparent = scene.render.film_transparent
    before_filepath = scene.render.filepath

    # The render failure inside the loop makes operator.execute() report an
    # ERROR and return CANCELLED, which bpy.ops re-raises as a RuntimeError
    # at the call site -- the same mechanism exercised above for the
    # missing-camera case.
    try:
        result = bpy.ops.rastersheet.render()
    except RuntimeError as exc:
        assert "cannot save" in str(exc).lower() or "render" in str(exc).lower(), exc
    else:
        raise AssertionError(f"expected the mid-loop render failure to raise, got {result}")

    assert (obj.matrix_world.to_translation() - before_matrix.to_translation()).length < 1e-6
    assert scene.render.engine == before_engine
    assert scene.render.resolution_x == before_res_x
    assert scene.render.resolution_y == before_res_y
    assert scene.render.film_transparent == before_film_transparent
    assert scene.render.filepath == before_filepath


def main():
    enable_addon()
    for fn in CHECKS:
        fn()
        print(f"  ok  {fn.__name__}")
    print("SMOKE OK")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        print("SMOKE FAIL")
        sys.exit(1)
