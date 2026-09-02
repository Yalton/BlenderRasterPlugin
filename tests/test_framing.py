import math

import pytest
from mathutils import Matrix, Vector

from rastersheet.core.framing import required_ortho_scale

# A camera 5 units up +Z, looking down -Z with +Y up.
CAMERA = Matrix.Translation(Vector((0.0, 0.0, 5.0)))
UNIT_CUBE = [
    Vector((x, y, z)) for x in (-0.5, 0.5) for y in (-0.5, 0.5) for z in (-0.5, 0.5)
]


def test_axis_aligned_unit_cube_needs_a_scale_of_one():
    scale = required_ortho_scale(UNIT_CUBE, CAMERA, [Matrix.Identity(4)], 1.0, 1.0)
    assert abs(scale - 1.0) < 1e-6


def test_forty_five_degrees_needs_the_diagonal():
    rotated = Matrix.Rotation(math.radians(45.0), 4, Vector((0.0, 0.0, 1.0)))
    scale = required_ortho_scale(UNIT_CUBE, CAMERA, [rotated], 1.0, 1.0)
    assert abs(scale - math.sqrt(2.0)) < 1e-6


def test_the_maximum_across_frames_wins_not_the_last_one():
    rotated = Matrix.Rotation(math.radians(45.0), 4, Vector((0.0, 0.0, 1.0)))
    scale = required_ortho_scale(UNIT_CUBE, CAMERA, [rotated, Matrix.Identity(4)], 1.0, 1.0)
    assert abs(scale - math.sqrt(2.0)) < 1e-6


def test_a_wide_aspect_widens_the_required_horizontal_extent():
    scale = required_ortho_scale(UNIT_CUBE, CAMERA, [Matrix.Identity(4)], 2.0, 1.0)
    assert abs(scale - 2.0) < 1e-6


def test_margin_scales_the_result():
    scale = required_ortho_scale(UNIT_CUBE, CAMERA, [Matrix.Identity(4)], 1.0, 1.2)
    assert abs(scale - 1.2) < 1e-6


def test_object_offset_from_the_camera_axis_still_fits():
    offset = Matrix.Translation(Vector((3.0, 0.0, 0.0)))
    scale = required_ortho_scale(UNIT_CUBE, CAMERA, [offset], 1.0, 1.0)
    assert abs(scale - 1.0) < 1e-6


def test_invalid_aspect_is_rejected():
    with pytest.raises(ValueError):
        required_ortho_scale(UNIT_CUBE, CAMERA, [Matrix.Identity(4)], 0.0, 1.0)


def test_no_frames_is_rejected():
    with pytest.raises(ValueError):
        required_ortho_scale(UNIT_CUBE, CAMERA, [], 1.0, 1.0)


def test_rotated_camera_exercises_inversion_code_path():
    # Camera rotated 45° around X-axis (tilted forward), positioned at (0, 0, 5).
    # This test verifies that the inversion code path is exercised.
    # Note: For a symmetric object centered at origin, the extent measurement is
    # invariant to inversion (it's an isometry). This test passes with or without
    # inversion because the mathematical invariant holds. It serves as a regression
    # test to ensure rotated cameras are handled consistently. Finding asymmetric-
    # object discrimination of inversion would require non-uniform objects, which
    # conflict with the UNIT_CUBE fixture design.
    camera_rotated = Matrix.Translation(Vector((0.0, 0.0, 5.0))) @ Matrix.Rotation(
        math.radians(45.0), 4, Vector((1.0, 0.0, 0.0))
    )
    scale = required_ortho_scale(UNIT_CUBE, camera_rotated, [Matrix.Identity(4)], 1.0, 1.0)
    # Height extent involves y and z: max(y*cos(45°) + z*sin(45°)) = √2
    assert abs(scale - math.sqrt(2.0)) < 1e-6


def test_per_frame_reduction_not_global_bounding_box():
    # Two frames with objects at different centers.
    # Frame 1: identity (object centered at origin).
    # Frame 2: translated by (2.0, 0.0, 0.0) (object offset in +X).
    # Per-frame approach: each frame needs scale 1.0. Maximum = 1.0.
    # Global bounding box approach (wrong): union of all corners is x from -0.5 to 2.5,
    # y from -0.5 to 0.5. Width = 3.0, height = 1.0. Max = 3.0.
    # This test ensures the function reduces per-frame, not globally.
    offset_frame = Matrix.Translation(Vector((2.0, 0.0, 0.0)))
    scale = required_ortho_scale(
        UNIT_CUBE, CAMERA, [Matrix.Identity(4), offset_frame], 1.0, 1.0
    )
    assert abs(scale - 1.0) < 1e-6


def test_compound_rotation_camera_with_asymmetric_corners_detects_missing_inversion():
    # Compound-rotation camera + asymmetric corners reliably detect missing inversion.
    # Single-axis rotations on symmetric objects hide the difference (R and R⁻¹ coincide
    # in their axis-aligned effects). Camera translations always cancel (translation
    # shifts all points equally; extent is max - min). Only compound rotations on
    # asymmetric objects break symmetry enough to discriminate.
    #
    # Camera: Translation(2, -4, 3) @ RotX(35°) @ RotZ(50°)
    # Wedge corners: [(0,0,0), (2,0,0), (0,1,0), (0,0,3), (0.3,0.7,1.1)]
    #
    # Expected (with inversion):
    # view = camera.inverted()
    # For each corner p: apply view @ p
    # x-extent ranges approximately -0.094 to 1.225, width ~ 1.318
    # y-extent ranges approximately 1.000 to 3.639, height ~ 2.638
    # needed = max(1.318, 2.638 * 1.0) = 2.638153
    #
    # Without inversion (buggy):
    # camera @ p (wrong transformation puts points in wrong space)
    # width ~ 2.052, height ~ 2.976
    # needed = max(2.052, 2.976) = 2.975744
    #
    # Difference: 0.3376 (large margin, cannot be swallowed by tolerance)
    wedge = [
        Vector((0.0, 0.0, 0.0)),
        Vector((2.0, 0.0, 0.0)),
        Vector((0.0, 1.0, 0.0)),
        Vector((0.0, 0.0, 3.0)),
        Vector((0.3, 0.7, 1.1)),
    ]

    camera_compound = (
        Matrix.Translation(Vector((2.0, -4.0, 3.0)))
        @ Matrix.Rotation(math.radians(35.0), 4, Vector((1.0, 0.0, 0.0)))
        @ Matrix.Rotation(math.radians(50.0), 4, Vector((0.0, 0.0, 1.0)))
    )

    scale = required_ortho_scale(wedge, camera_compound, [Matrix.Identity(4)], 1.0, 1.0)
    # Expected (with inversion): 2.638153
    assert abs(scale - 2.638153) < 1e-5
