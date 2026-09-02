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


def test_the_union_of_frames_is_covered_not_the_widest_single_frame():
    # This test previously asserted the opposite (a per-frame maximum of 1.0),
    # and that expectation was wrong -- do not re-derive it. The fixture is
    # kept because it is exactly the case where the two formulas disagree:
    #
    #   Frame 1: identity            -- cube centred at the origin.
    #   Frame 2: translated (2, 0, 0) -- the same cube, moved.
    #
    # Per-frame maximum: each frame is 1.0 wide on its own, so max = 1.0.
    # Union: x runs from -0.5 to 2.5, so width = 3.0.
    #
    # The union is what must be covered, because `camera.py` places ONE camera
    # at the centre of the union of all frames and renders every frame through
    # it. A scale of 1.0 here frames frame 1 and leaves frame 2 entirely
    # outside the view. The per-frame maximum is only sufficient when every
    # frame shares a camera-space centre, which is exactly what an orbiting
    # subject (the default ORIGIN pivot on an off-centre mesh) does not do.
    offset_frame = Matrix.Translation(Vector((2.0, 0.0, 0.0)))
    scale = required_ortho_scale(
        UNIT_CUBE, CAMERA, [Matrix.Identity(4), offset_frame], 1.0, 1.0
    )
    assert abs(scale - 3.0) < 1e-6


def test_an_orbiting_subject_needs_its_swept_extent():
    # The defect the union formula fixes, reproduced at the defaults that
    # trigger it: a unit cube whose mesh is shifted (0.35, 0, 0) in local
    # space, rotated a full 360 degrees about the object ORIGIN over 8 frames.
    # The cube orbits rather than spinning in place, so per-frame extents stay
    # at sqrt(2) while the per-frame centres move; the fixed camera needs
    # 1.9092. The shortfall is 1.35x, which the default 1.2 margin does not
    # absorb -- 4 of 8 rendered frames were clipped.
    offset_cube = [
        Vector((x + 0.35, y, z))
        for x in (-0.5, 0.5)
        for y in (-0.5, 0.5)
        for z in (-0.5, 0.5)
    ]
    frames = [
        Matrix.Rotation(2.0 * math.pi * index / 8.0, 4, Vector((0.0, 0.0, 1.0)))
        for index in range(8)
    ]
    scale = required_ortho_scale(offset_cube, CAMERA, frames, 1.0, 1.0)
    assert abs(scale - 1.909188) < 1e-5
    # Not merely "bigger than one frame": strictly bigger than the widest
    # single pose, which is what the old formula returned.
    assert scale > math.sqrt(2.0) + 0.01


def test_a_subject_spinning_in_place_costs_nothing():
    # The union is strictly safer and free in the common case: the swept extent
    # of a shape rotating about its own centre equals its widest single pose,
    # so the union returns exactly what the old per-frame maximum returned
    # (verified bit-identical: 1.4142136573791504 from both formulas).
    frames = [
        Matrix.Rotation(2.0 * math.pi * index / 8.0, 4, Vector((0.0, 0.0, 1.0)))
        for index in range(8)
    ]
    union = required_ortho_scale(UNIT_CUBE, CAMERA, frames, 1.0, 1.0)
    assert abs(union - math.sqrt(2.0)) < 1e-6
    # And nothing was padded on: the whole sweep costs no more than the single
    # widest pose in it.
    assert union == max(
        required_ortho_scale(UNIT_CUBE, CAMERA, [frame], 1.0, 1.0) for frame in frames
    )


def test_compound_rotation_camera_with_asymmetric_corners_detects_missing_inversion():
    # Compound-rotation camera + asymmetric corners reliably detect missing inversion.
    # This is the ONLY inversion test in this file. A tilted-camera-plus-symmetric-cube
    # variant used to sit above it, carrying a comment claiming asymmetric-object
    # discrimination "would require non-uniform objects"; this test is the
    # counter-example that disproves that claim, so the inert test was deleted rather
    # than left in place to have its wrong explanation re-derived.
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
