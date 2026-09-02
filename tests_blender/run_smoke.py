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


def _ensure_probe_camera(scene):
    camera = bpy.data.objects.get("ProbeCam")
    if camera is None:
        camera_data = bpy.data.cameras.new("ProbeCam")
        camera = bpy.data.objects.new("ProbeCam", camera_data)
        scene.collection.objects.link(camera)
    camera.location = (0.0, -5.0, 0.0)
    camera.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    scene.camera = camera
    return camera


def _matrices_close(a, b, tol=1e-6):
    """Component-wise comparison of the full 4x4 matrix, not just translation.

    Comparing only `to_translation()` is blind to rotation: under the
    default ORIGIN pivot, translation is mathematically constant across the
    entire frame loop (T(pivot) @ R @ T(-pivot) @ base leaves the
    translation column untouched at every angle), so a translation-only
    check passes even if the object is left mid-spin with restoration
    completely broken.
    """
    for row_a, row_b in zip(a, b):
        for value_a, value_b in zip(row_a, row_b):
            if abs(value_a - value_b) > tol:
                return False
    return True


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
    _ensure_probe_camera(scene)

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

    assert _matrices_close(obj.matrix_world, before_matrix), (tuple(obj.matrix_world), tuple(before_matrix))
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

    assert _matrices_close(obj.matrix_world, before_matrix), (tuple(obj.matrix_world), tuple(before_matrix))
    assert scene.render.engine == before_engine
    assert scene.render.resolution_x == before_res_x
    assert scene.render.resolution_y == before_res_y
    assert scene.render.film_transparent == before_film_transparent
    assert scene.render.filepath == before_filepath


@check
def test_sheet_packing_is_pixel_identical_to_its_frames():
    import numpy as np
    import shutil

    scene = bpy.context.scene

    # The default startup scene ships a "Cube" object sitting at the origin,
    # exactly coincident with the probe cube _fresh_cube() creates there. It
    # is never rotated, so if left in place it renders identically into
    # every frame and silently masks any visual difference the probe's
    # rotation would otherwise produce (confirmed by direct A/B render: with
    # this object present, rotating the probe by any angle -- including 50
    # degrees, nowhere near a cube symmetry -- still produced bit-identical
    # frames). Remove it so the probe's rotation is what actually gets
    # rendered.
    default_cube = bpy.data.objects.get("Cube")
    if default_cube is not None:
        bpy.data.objects.remove(default_cube, do_unlink=True)

    obj = _fresh_cube()
    bpy.context.view_layer.objects.active = obj
    _ensure_probe_camera(scene)

    out = os.path.join(SCRATCH, "sheet_run")
    shutil.rmtree(out, ignore_errors=True)

    settings = scene.rastersheet
    # 4 frames / 2 columns -> 2 rows. A single-row layout has every cell.y
    # == 0, which makes the sheet_height - cell.y - cell.height flip in
    # packing.py a no-op and leaves a broken flip undetected.
    settings.frame_count = 4
    settings.columns = 2
    settings.sheet_mode = "GRID"
    # A full 360 degree sweep over 4 frames lands on exactly 0/90/180/270
    # degrees -- and rotating an axis-aligned, uniformly-shaded cube by any
    # multiple of 90 degrees about a face-normal axis (every axis this
    # add-on offers is one) is a genuine geometric symmetry: the solid maps
    # exactly onto itself, so the render is bit-identical regardless of
    # which of those four angles was used (confirmed by direct A/B render).
    # A partial, non-90-multiple sweep avoids landing on any of the cube's
    # symmetry angles, so consecutive frames are guaranteed to look
    # genuinely different.
    settings.start_angle = 0.0
    settings.sweep_angle = math.radians(200.0)
    settings.resolution_mode = "CUSTOM"
    settings.resolution_x = 32
    settings.resolution_y = 32
    settings.output_dir = out
    settings.filename_stem = "sheet"
    settings.export_frames = True
    settings.export_sheet = True
    settings.export_json = False
    settings.export_godot = False
    settings.camera_mode = "CURRENT"

    assert bpy.ops.rastersheet.render() == {"FINISHED"}

    sheet_path = os.path.join(out, "sheet.png")
    assert os.path.isfile(sheet_path)

    sheet = bpy.data.images.load(sheet_path)
    frames = [
        bpy.data.images.load(os.path.join(out, "sheet_frames", f"sheet_{index + 1:04d}.png"))
        for index in range(4)
    ]
    try:
        assert tuple(sheet.size) == (64, 64), tuple(sheet.size)

        # Sanity check only: this does NOT verify pack_sheet's colorspace
        # handling. Both images were just independently reloaded from disk,
        # so each carries Blender's default colorspace heuristic for a PNG
        # regardless of what pack_sheet assigned -- it would pass identically
        # even if the `sheet.colorspace_settings.name = colorspace` line in
        # packing.py were deleted. The pixel round-trip below, over content
        # asserted to be non-degenerate, is what actually exercises that.
        assert sheet.colorspace_settings.name == frames[0].colorspace_settings.name

        sheet_pixels = np.empty(64 * 64 * 4, dtype=np.float32)
        sheet.pixels.foreach_get(sheet_pixels)
        sheet_pixels = sheet_pixels.reshape(64, 64, 4)

        frame_arrays = []
        for frame in frames:
            buffer = np.empty(32 * 32 * 4, dtype=np.float32)
            frame.pixels.foreach_get(buffer)
            frame_arrays.append(buffer.reshape(32, 32, 4))

        # A round-trip over degenerate content (flat 0 or flat 1) would pass
        # regardless of colorspace or flip correctness, since such values map
        # to themselves under any transform and any row placement. Assert the
        # probe frame actually carries intermediate values in both colour and
        # alpha before trusting the comparison below.
        probe = frame_arrays[2]
        assert np.any((probe[..., :3] > 1e-3) & (probe[..., :3] < 1 - 1e-3)), \
            "frame has no intermediate colour values to exercise a real comparison"
        assert np.any((probe[..., 3] > 1e-3) & (probe[..., 3] < 1 - 1e-3)), \
            "frame has no intermediate alpha values to exercise a real comparison"

        # Frame index 2 occupies the layout's bottom-left cell (cell.y ==
        # frame_height, the second row, top-left origin). A correct flip
        # (sheet_height - cell.y - cell.height) puts it in the LOW index
        # range of Blender's bottom-up buffer; a no-op flip (bottom =
        # cell.y) would instead put it in the HIGH range, where frame 0
        # belongs -- so this discriminates a broken flip.
        region_2 = sheet_pixels[0:32, 0:32]
        assert np.allclose(region_2, frame_arrays[2], atol=1e-6), np.abs(region_2 - frame_arrays[2]).max()

        # Frame 0 occupies the top-left cell (first row, cell.y == 0) and
        # must land in the HIGH index range -- the opposite half.
        region_0 = sheet_pixels[32:64, 0:32]
        assert np.allclose(region_0, frame_arrays[0], atol=1e-6), np.abs(region_0 - frame_arrays[0]).max()
    finally:
        bpy.data.images.remove(sheet)
        for frame in frames:
            bpy.data.images.remove(frame)


@check
def test_sheet_only_export_leaves_no_frames_directory():
    import shutil

    scene = bpy.context.scene
    obj = _fresh_cube()
    bpy.context.view_layer.objects.active = obj
    _ensure_probe_camera(scene)

    out = os.path.join(SCRATCH, "sheet_only_run")
    shutil.rmtree(out, ignore_errors=True)

    settings = scene.rastersheet
    settings.frame_count = 2
    settings.columns = 2
    settings.output_dir = out
    settings.filename_stem = "only"
    settings.export_frames = False
    settings.export_sheet = True

    assert bpy.ops.rastersheet.render() == {"FINISHED"}
    assert os.path.isfile(os.path.join(out, "only.png"))
    assert not os.path.exists(os.path.join(out, "only_frames"))


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
