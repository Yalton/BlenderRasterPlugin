import math

import pytest
from mathutils import Matrix, Vector

from rastersheet.core.rotation import axis_vector, frame_matrix

HALF_TURN_QUARTER = math.radians(90.0)


def approx(vector, expected):
    return all(abs(a - b) < 1e-6 for a, b in zip(vector, expected))


def test_world_axis_ignores_the_object_transform():
    base = Matrix.Rotation(HALF_TURN_QUARTER, 4, Vector((1.0, 0.0, 0.0)))
    assert approx(axis_vector("WORLD_Y", base), (0.0, 1.0, 0.0))


def test_local_axis_follows_the_object_transform():
    # Rotating 90 degrees about X carries local +Y onto world +Z.
    base = Matrix.Rotation(HALF_TURN_QUARTER, 4, Vector((1.0, 0.0, 0.0)))
    assert approx(axis_vector("LOCAL_Y", base), (0.0, 0.0, 1.0))


def test_unknown_axis_is_rejected():
    with pytest.raises(ValueError):
        axis_vector("DIAGONAL_Q", Matrix.Identity(4))


def test_rotation_about_the_object_origin_moves_it_around_the_world_origin():
    base = Matrix.Translation(Vector((5.0, 0.0, 0.0)))
    result = frame_matrix(base, Vector((0.0, 0.0, 1.0)), HALF_TURN_QUARTER, Vector((0.0, 0.0, 0.0)))
    assert approx(result.to_translation(), (0.0, 5.0, 0.0))


def test_rotation_about_its_own_pivot_leaves_the_object_in_place():
    base = Matrix.Translation(Vector((5.0, 0.0, 0.0)))
    pivot = Vector((5.0, 0.0, 0.0))
    result = frame_matrix(base, Vector((0.0, 0.0, 1.0)), HALF_TURN_QUARTER, pivot)
    assert approx(result.to_translation(), (5.0, 0.0, 0.0))


def test_zero_angle_reproduces_the_base_matrix():
    base = Matrix.Translation(Vector((1.0, 2.0, 3.0)))
    result = frame_matrix(base, Vector((0.0, 0.0, 1.0)), 0.0, Vector((0.0, 0.0, 0.0)))
    for row_result, row_base in zip(result, base):
        assert approx(row_result, row_base)


def test_operand_order_with_rotated_base_and_nonzero_pivot():
    # This test discriminates between the correct formula
    # T(pivot) @ R @ T(-pivot) @ base_matrix and incorrectly swapped orderings.
    # It uses a rotated base_matrix and non-origin pivot so the two orderings diverge.
    base = Matrix.Rotation(HALF_TURN_QUARTER, 4, Vector((0.0, 1.0, 0.0)))
    pivot = Vector((1.0, 0.0, 0.0))
    axis_world = Vector((0.0, 0.0, 1.0))
    angle = HALF_TURN_QUARTER

    # Compute expected value using the correct formula verbatim
    expected = (Matrix.Translation(pivot) @
                Matrix.Rotation(angle, 4, axis_world) @
                Matrix.Translation(-pivot) @
                base)

    # Get result from function
    result = frame_matrix(base, axis_world, angle, pivot)

    # Verify the full matrices match
    for row_result, row_expected in zip(result, expected):
        assert approx(row_result, row_expected)
