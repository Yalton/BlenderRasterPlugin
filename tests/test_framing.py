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
