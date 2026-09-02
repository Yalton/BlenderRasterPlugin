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


def _reset_settings():
    """Return every rastersheet setting to its declared default.

    Without this, checks silently inherit whatever the previous check left
    behind -- there is no other reset anywhere in this runner, and property
    values on scene.rastersheet persist for the lifetime of the Blender
    process. property_unset() is Blender's own "go back to the property's
    declared default" primitive; iterating bl_rna.properties (skipping the
    handful that are read-only, like rna_type) unsets everything without
    this function needing to know the property list by name.
    """
    settings = bpy.context.scene.rastersheet
    for prop in settings.bl_rna.properties:
        if prop.is_readonly:
            continue
        settings.property_unset(prop.identifier)


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
    # settings.lighting_mode defaults to MATERIAL_PREVIEW (reset by
    # _reset_settings() before this check runs), so this run's snapshot
    # builds a temporary world -- "an aborted run leaves no orphans in
    # bpy.data" is a named global constraint, and this is the only check
    # that induces a genuine mid-loop failure through the full operator, so
    # it is where that constraint actually gets exercised.
    before_world = scene.world
    before_worlds = len(bpy.data.worlds)
    before_images = len(bpy.data.images)

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
    assert scene.world == before_world
    assert len(bpy.data.worlds) == before_worlds, "temp world orphaned after a mid-loop failure"
    assert len(bpy.data.images) == before_images, "loaded HDRI/studio image orphaned after a mid-loop failure"


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


@check
def test_direction_and_angles_round_trip():
    from bl_ext.user_default.rastersheet.blender import camera as camera_module

    for azimuth, elevation in [(0.0, 0.0), (90.0, 0.0), (0.0, 30.0), (215.0, -45.0)]:
        direction = camera_module.direction_from(azimuth, elevation)
        back_az, back_el = camera_module.angles_from_direction(direction)
        assert abs(((back_az - azimuth + 180.0) % 360.0) - 180.0) < 1e-4, (azimuth, back_az)
        assert abs(back_el - elevation) < 1e-4, (elevation, back_el)


@check
def test_front_view_is_down_the_negative_y_axis():
    from bl_ext.user_default.rastersheet.blender import camera as camera_module

    direction = camera_module.direction_from(0.0, 0.0)
    assert abs(direction.x) < 1e-6
    assert abs(direction.y + 1.0) < 1e-6
    assert abs(direction.z) < 1e-6


@check
def test_auto_ortho_keeps_the_object_off_the_border_at_every_angle():
    import numpy as np
    import shutil

    scene = bpy.context.scene
    obj = _fresh_cube()
    # Move the object well away from the world origin: auto framing must not
    # depend on the object sitting at (0, 0, 0).
    obj.matrix_world = mathutils.Matrix.Translation((7.0, -3.0, 2.0))
    bpy.context.view_layer.objects.active = obj

    out = os.path.join(SCRATCH, "ortho_run")
    shutil.rmtree(out, ignore_errors=True)

    settings = scene.rastersheet
    settings.camera_mode = "AUTO_ORTHO"
    settings.azimuth = 0.0
    settings.elevation = 30.0
    settings.camera_margin = 1.2
    settings.pivot_mode = "BOUNDS_CENTER"
    settings.frame_count = 4
    settings.columns = 2
    settings.start_angle = 0.0
    # This test does not set rotation_axis, so it runs on whatever
    # main()'s per-check reset leaves as the declared default: LOCAL_Y
    # (verified directly -- see the task 11 fix report). The default sweep
    # (360 degrees over 4 frames) steps in exact 90-degree increments about
    # the cube's own centre on that axis -- a rotational symmetry of a
    # cube, so all four frames rendered bit-identical geometry (confirmed
    # by comparing world-space corner sets: they matched exactly). A sweep
    # whose steps are not multiples of 90 degrees makes the cube's square
    # cross-section trace a genuinely different (wider, "diamond")
    # axis-aligned footprint at each angle instead. Verified this holds for
    # this exact axis/pivot combination -- see the fix report for task 11
    # for the corner-set and rendered-pixel diffs.
    settings.sweep_angle = math.radians(250.0)
    settings.resolution_mode = "CUSTOM"
    settings.resolution_x = 64
    settings.resolution_y = 64
    settings.output_dir = out
    settings.filename_stem = "ortho"
    settings.export_frames = True
    settings.export_sheet = False
    settings.transparent = True

    before_camera = scene.camera
    before_cameras = len(bpy.data.cameras)

    assert bpy.ops.rastersheet.render() == {"FINISHED"}

    assert scene.camera == before_camera
    assert len(bpy.data.cameras) == before_cameras

    for index in range(1, 5):
        path = os.path.join(out, "ortho_frames", f"ortho_{index:04d}.png")
        image = bpy.data.images.load(path)
        try:
            pixels = np.empty(64 * 64 * 4, dtype=np.float32)
            image.pixels.foreach_get(pixels)
            alpha = pixels.reshape(64, 64, 4)[:, :, 3]
            assert alpha.max() > 0.5, f"frame {index} is empty"
            border = np.concatenate([alpha[0, :], alpha[-1, :], alpha[:, 0], alpha[:, -1]])
            assert border.max() < 0.01, f"frame {index} touches the border"
        finally:
            bpy.data.images.remove(image)


@check
def test_auto_ortho_recenters_a_subject_whose_origin_is_off_its_bounds_center():
    # The check above cannot exercise the recentring correction at all: with
    # BOUNDS_CENTER pivot, the rotation pivot IS the bound_box's own centre,
    # so bound_box (always an axis-aligned, self-symmetric box) stays exactly
    # symmetric about that pivot at every angle -- the measured residual
    # offset is mathematically zero regardless of whether the correction
    # code runs at all (confirmed by direct bug injection: deleting the
    # offset step left that check still green). Discriminating the fix
    # requires a pivot that does NOT coincide with the object's own bounds
    # centre, which only happens with ORIGIN pivot on a mesh whose geometry
    # isn't centred on the object's origin -- built here by shifting the
    # mesh data (not the object) after creation.
    import numpy as np
    import shutil
    import bmesh

    scene = bpy.context.scene
    name = "RasterSheetOffsetProbe"
    existing = bpy.data.objects.get(name)
    if existing:
        bpy.data.objects.remove(existing, do_unlink=True)
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(obj)
    # Shift the mesh data in local space, leaving the object's origin at
    # local (0, 0, 0) -- so the bound_box centre no longer coincides with
    # the ORIGIN pivot used below.
    obj.data.transform(mathutils.Matrix.Translation((0.35, 0.0, 0.0)))
    # A location distinct from every other probe object's position elsewhere
    # in this suite (several of which are never cleaned up): auto framing
    # only looks at the active object's own bounds, so any leftover probe
    # sharing this camera's tightly-fit frame would render into it too and
    # corrupt the border check below.
    obj.matrix_world = mathutils.Matrix.Translation((-40.0, 25.0, -10.0))
    bpy.context.view_layer.objects.active = obj

    out = os.path.join(SCRATCH, "ortho_offset_run")
    shutil.rmtree(out, ignore_errors=True)

    settings = scene.rastersheet
    settings.camera_mode = "AUTO_ORTHO"
    settings.azimuth = 60.0
    settings.elevation = 10.0
    settings.camera_margin = 1.15
    settings.pivot_mode = "ORIGIN"
    settings.rotation_axis = "WORLD_Z"
    settings.frame_count = 4
    settings.columns = 2
    settings.start_angle = 0.0
    # A small, non-multiple-of-90 sweep: large enough that the object's
    # off-centre geometry sweeps out a genuinely asymmetric silhouette (so a
    # missing recentring correction visibly clips), small enough that a
    # single whole-sheet correction still covers every frame when it IS
    # applied (this is not a claim that the fix handles arbitrary sweeps --
    # only that it must handle this one).
    settings.sweep_angle = math.radians(30.0)
    settings.resolution_mode = "CUSTOM"
    settings.resolution_x = 64
    settings.resolution_y = 64
    settings.output_dir = out
    settings.filename_stem = "offset"
    settings.export_frames = True
    settings.export_sheet = False
    settings.transparent = True

    before_camera = scene.camera
    before_cameras = len(bpy.data.cameras)

    assert bpy.ops.rastersheet.render() == {"FINISHED"}

    assert scene.camera == before_camera
    assert len(bpy.data.cameras) == before_cameras

    for index in range(1, 5):
        path = os.path.join(out, "offset_frames", f"offset_{index:04d}.png")
        image = bpy.data.images.load(path)
        try:
            pixels = np.empty(64 * 64 * 4, dtype=np.float32)
            image.pixels.foreach_get(pixels)
            alpha = pixels.reshape(64, 64, 4)[:, :, 3]
            assert alpha.max() > 0.5, f"frame {index} is empty"
            border = np.concatenate([alpha[0, :], alpha[-1, :], alpha[:, 0], alpha[:, -1]])
            assert border.max() < 0.01, f"frame {index} touches the border"
        finally:
            bpy.data.images.remove(image)


@check
def test_lighting_modes_all_render_and_restore_the_world():
    import shutil

    scene = bpy.context.scene
    obj = _fresh_cube()
    obj.matrix_world = mathutils.Matrix.Identity(4)
    bpy.context.view_layer.objects.active = obj
    _ensure_probe_camera(scene)

    settings = scene.rastersheet
    settings.camera_mode = "CURRENT"
    settings.frame_count = 2
    settings.columns = 2
    settings.resolution_mode = "CUSTOM"
    settings.resolution_x = 16
    settings.resolution_y = 16
    settings.export_frames = True
    settings.export_sheet = False

    before_world = scene.world
    before_worlds = len(bpy.data.worlds)

    for mode in ["MATERIAL_PREVIEW", "SCENE_WORLD", "SCENE_LIGHTS", "FLAT"]:
        out = os.path.join(SCRATCH, f"light_{mode.lower()}")
        shutil.rmtree(out, ignore_errors=True)
        settings.lighting_mode = mode
        settings.output_dir = out
        settings.filename_stem = "light"
        assert bpy.ops.rastersheet.render() == {"FINISHED"}, mode
        assert os.path.isfile(os.path.join(out, "light_frames", "light_0001.png")), mode
        assert scene.world == before_world, mode
        assert len(bpy.data.worlds) == before_worlds, mode


@check
def test_apply_lighting_builds_the_expected_world_per_mode():
    # The end-to-end check above only proves a file gets written and the
    # world is restored afterwards -- both true even if apply_lighting were
    # a no-op, since SCENE_WORLD is already a no-op and a render succeeds
    # regardless of what lights the scene. This check calls apply_lighting
    # directly and inspects the temporary world's node values before
    # unwinding, so it actually distinguishes SCENE_LIGHTS (black
    # background) from FLAT (white background) from MATERIAL_PREVIEW (an
    # environment texture, or a white fallback with no bundled studio
    # light), and confirms SCENE_WORLD builds nothing at all.
    import contextlib

    from bl_ext.user_default.rastersheet.blender import lighting as lighting_module
    from bl_ext.user_default.rastersheet.blender import snapshot as snapshot_module

    scene = bpy.context.scene
    settings = scene.rastersheet
    before_world = scene.world
    before_worlds = len(bpy.data.worlds)
    before_images = len(bpy.data.images)

    with contextlib.ExitStack() as stack:
        snapshot_module.guard(stack, scene, "world")
        settings.lighting_mode = "SCENE_WORLD"
        lighting_module.apply_lighting(bpy.context, settings, stack)
        assert scene.world == before_world
        assert len(bpy.data.worlds) == before_worlds

    color_cases = {
        "SCENE_LIGHTS": lighting_module.BLACK,
        "FLAT": lighting_module.WHITE,
    }
    for mode, expected_color in color_cases.items():
        with contextlib.ExitStack() as stack:
            snapshot_module.guard(stack, scene, "world")
            settings.lighting_mode = mode
            lighting_module.apply_lighting(bpy.context, settings, stack)
            world = scene.world
            assert world != before_world, mode
            assert len(bpy.data.worlds) == before_worlds + 1, mode
            background = world.node_tree.nodes["Background"]
            assert tuple(background.inputs["Color"].default_value) == expected_color, mode
            assert background.inputs["Strength"].default_value == 1.0, mode
        assert scene.world == before_world, mode
        assert len(bpy.data.worlds) == before_worlds, mode

    with contextlib.ExitStack() as stack:
        snapshot_module.guard(stack, scene, "world")
        settings.lighting_mode = "MATERIAL_PREVIEW"
        lighting_module.apply_lighting(bpy.context, settings, stack)
        world = scene.world
        assert world != before_world
        tree = world.node_tree
        background = tree.nodes["Background"]
        environment_nodes = [n for n in tree.nodes if n.type == "TEX_ENVIRONMENT"]
        if settings.studio_light not in {"", "NONE"}:
            assert environment_nodes, "expected a bundled studio HDRI to attach"
            assert environment_nodes[0].image is not None
            assert len(bpy.data.images) == before_images + 1
        else:
            assert not environment_nodes
            assert tuple(background.inputs["Color"].default_value) == lighting_module.WHITE
    assert scene.world == before_world
    assert len(bpy.data.worlds) == before_worlds
    assert len(bpy.data.images) == before_images


@check
def test_custom_hdri_wires_the_users_image_and_strength():
    # CUSTOM_HDRI has zero coverage anywhere else: MATERIAL_PREVIEW exercises
    # the shared _attach_environment helper via a bundled studio light, but
    # this mode's own wiring -- bpy.path.abspath(settings.hdri_path) and
    # settings.hdri_strength -- is untested, and it is a user-facing mode.
    # Generate a throwaway image with non-uniform pixel content (so "some
    # image got loaded" can't be confused with "the right image got
    # loaded"), save it to scratch as a real file Blender can load back, and
    # assert the temp world's environment node is wired to exactly that
    # image and that Background strength reflects hdri_strength (2.5) rather
    # than the hardcoded 1.0 the MATERIAL_PREVIEW path always uses.
    import contextlib

    from bl_ext.user_default.rastersheet.blender import lighting as lighting_module
    from bl_ext.user_default.rastersheet.blender import snapshot as snapshot_module

    path = os.path.join(SCRATCH, "smoke_custom_hdri.png")
    generator = bpy.data.images.new("RasterSheetSmokeHDRIGen", width=4, height=4, alpha=False)
    pixels = [0.0] * (4 * 4 * 4)
    for y in range(4):
        for x in range(4):
            i = (y * 4 + x) * 4
            checker = (x + y) % 2 == 0
            pixels[i + 0] = 1.0 if checker else 0.0
            pixels[i + 1] = 0.0
            pixels[i + 2] = 0.0 if checker else 1.0
            pixels[i + 3] = 1.0
    generator.pixels.foreach_set(pixels)
    generator.filepath_raw = path
    generator.file_format = "PNG"
    generator.save()
    bpy.data.images.remove(generator)

    scene = bpy.context.scene
    settings = scene.rastersheet
    before_world = scene.world
    before_worlds = len(bpy.data.worlds)
    before_images = len(bpy.data.images)

    settings.lighting_mode = "CUSTOM_HDRI"
    settings.hdri_path = path
    settings.hdri_strength = 2.5

    with contextlib.ExitStack() as stack:
        snapshot_module.guard(stack, scene, "world")
        lighting_module.apply_lighting(bpy.context, settings, stack)
        world = scene.world
        assert world != before_world
        assert len(bpy.data.worlds) == before_worlds + 1
        assert len(bpy.data.images) == before_images + 1

        tree = world.node_tree
        background = tree.nodes["Background"]
        environment_nodes = [n for n in tree.nodes if n.type == "TEX_ENVIRONMENT"]
        assert len(environment_nodes) == 1
        loaded_image = environment_nodes[0].image
        assert loaded_image is not None
        assert os.path.abspath(bpy.path.abspath(loaded_image.filepath)) == os.path.abspath(path)

        # The Background input's *link* is what actually drives the shader
        # once a texture node feeds it -- not just leaving its unused
        # default_value at whatever it was, so assert the link exists and
        # comes from this environment node.
        color_links = background.inputs["Color"].links
        assert color_links and color_links[0].from_node == environment_nodes[0]

        assert background.inputs["Strength"].default_value == 2.5

    assert scene.world == before_world
    assert len(bpy.data.worlds) == before_worlds
    assert len(bpy.data.images) == before_images


@check
def test_view_transform_override_is_applied_and_restored():
    import shutil

    scene = bpy.context.scene
    obj = _fresh_cube()
    bpy.context.view_layer.objects.active = obj
    _ensure_probe_camera(scene)

    scene.view_settings.view_transform = "AgX"
    settings = scene.rastersheet
    settings.lighting_mode = "FLAT"
    settings.view_transform_mode = "STANDARD"
    settings.camera_mode = "CURRENT"
    settings.frame_count = 2
    settings.resolution_mode = "CUSTOM"
    settings.resolution_x = 16
    settings.resolution_y = 16
    out = os.path.join(SCRATCH, "vt_run")
    shutil.rmtree(out, ignore_errors=True)
    settings.output_dir = out
    settings.filename_stem = "vt"
    settings.export_frames = True
    settings.export_sheet = False

    # Asserting only pre- and post-render equality to "AgX" cannot tell "the
    # override was applied during the render, then restored" apart from
    # "the override was never applied at all" -- both leave the same before
    # and after value. A render_pre handler samples the live value at the
    # moment Blender is actually about to render each frame, which can only
    # read "Standard" if run() really assigned it.
    seen_during_render = []

    def _spy(*_args):
        seen_during_render.append(bpy.context.scene.view_settings.view_transform)

    bpy.app.handlers.render_pre.append(_spy)
    try:
        assert bpy.ops.rastersheet.render() == {"FINISHED"}
    finally:
        bpy.app.handlers.render_pre.remove(_spy)

    assert seen_during_render, "render_pre handler never fired"
    assert all(value == "Standard" for value in seen_during_render), seen_during_render
    assert scene.view_settings.view_transform == "AgX"


@check
def test_engine_override_resolves_and_restores():
    import shutil

    from bl_ext.user_default.rastersheet.blender import operator as operator_module

    scene = bpy.context.scene
    obj = _fresh_cube()
    bpy.context.view_layer.objects.active = obj
    _ensure_probe_camera(scene)

    resolved = operator_module.resolve_engine(scene, "EEVEE")
    assert resolved in {"BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"}, resolved

    before_engine = scene.render.engine
    settings = scene.rastersheet
    settings.engine_mode = "EEVEE"
    settings.lighting_mode = "FLAT"
    settings.camera_mode = "CURRENT"
    settings.frame_count = 2
    settings.resolution_mode = "CUSTOM"
    settings.resolution_x = 16
    settings.resolution_y = 16
    out = os.path.join(SCRATCH, "engine_run")
    shutil.rmtree(out, ignore_errors=True)
    settings.output_dir = out
    settings.filename_stem = "engine"
    settings.export_frames = True
    settings.export_sheet = False

    # Same reasoning as the view-transform check above: sample the live
    # engine at the moment of each actual render call, not just before and
    # after, so a deleted assignment (which would leave before == after too)
    # cannot pass silently.
    seen_during_render = []

    def _spy(*_args):
        seen_during_render.append(bpy.context.scene.render.engine)

    bpy.app.handlers.render_pre.append(_spy)
    try:
        assert bpy.ops.rastersheet.render() == {"FINISHED"}
    finally:
        bpy.app.handlers.render_pre.remove(_spy)

    assert seen_during_render, "render_pre handler never fired"
    assert all(value == resolved for value in seen_during_render), seen_during_render
    assert scene.render.engine == before_engine


def main():
    enable_addon()
    for fn in CHECKS:
        _reset_settings()
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
