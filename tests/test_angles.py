import math

import pytest

from rastersheet.core.angles import frame_angles


def degrees(values):
    return [round(math.degrees(v), 6) for v in values]


def test_full_turn_does_not_duplicate_the_wrap_frame():
    assert degrees(frame_angles(4, 0.0, 360.0, clockwise=False)) == [0.0, 90.0, 180.0, 270.0]


def test_partial_sweep_includes_both_endpoints():
    assert degrees(frame_angles(4, 0.0, 90.0, clockwise=False)) == [0.0, 30.0, 60.0, 90.0]


def test_clockwise_negates_the_progression_but_not_the_start():
    assert degrees(frame_angles(4, 0.0, 360.0, clockwise=True)) == [0.0, -90.0, -180.0, -270.0]


def test_start_angle_offsets_every_frame():
    assert degrees(frame_angles(2, 45.0, 180.0, clockwise=False)) == [45.0, 225.0]


def test_multiple_of_360_counts_as_a_full_turn():
    assert degrees(frame_angles(4, 0.0, 720.0, clockwise=False)) == [0.0, 180.0, 360.0, 540.0]


def test_count_below_two_is_rejected():
    with pytest.raises(ValueError):
        frame_angles(1, 0.0, 360.0, clockwise=False)
