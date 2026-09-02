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


def test_float32_rounded_360_is_classified_as_full_turn():
    # Blender stores as float32: radians(360) becomes 360.00001 on round-trip
    float32_360 = 360.00001001791264
    angles = frame_angles(4, 0.0, float32_360, clockwise=False)
    # Should use full-turn step (360.00001 / 4 ≈ 90.00000) not partial-arc step (360.00001 / 3 ≈ 120)
    # Verify by checking the step between consecutive frames is ~90 degrees, not ~120
    step_deg = round(math.degrees(angles[1]), 1)
    assert step_deg == 90.0, f"Expected step ~90° for full turn, got {step_deg}°"


def test_value_slightly_under_multiple_of_360_is_full_turn():
    # Rounding error can land below the multiple; tolerance should catch it
    slightly_under_720 = 720.0 - 1e-5
    angles = frame_angles(4, 0.0, slightly_under_720, clockwise=False)
    # Should use full-turn step (720 / 4 = 180) not partial-arc step (720 / 3 ≈ 240)
    step_deg = round(math.degrees(angles[1]), 1)
    assert step_deg == 180.0, f"Expected step ~180° for full turn, got {step_deg}°"


def test_partial_sweep_with_tolerance_still_includes_endpoints():
    # Partial sweep 359.0 should still be partial arc, not misclassified as full turn
    assert degrees(frame_angles(4, 0.0, 359.0, clockwise=False)) == [0.0, 119.666667, 239.333333, 359.0]


def test_near_zero_sweep_is_not_full_turn():
    # A very small sweep should not be classified as a full turn
    # (the tolerance guards against this by requiring sweep > tolerance)
    assert degrees(frame_angles(2, 0.0, 0.0001, clockwise=False)) == [0.0, 0.0001]


def test_negative_full_turn_does_not_duplicate_the_wrap_frame():
    # Negative sweep should also be classified as full turn
    assert degrees(frame_angles(4, 0.0, -360.0, clockwise=False)) == [0.0, -90.0, -180.0, -270.0]


def test_negative_multiple_of_360_counts_as_a_full_turn():
    # Negative sweep that is a multiple of 360 should be full turn
    assert degrees(frame_angles(4, 0.0, -720.0, clockwise=False)) == [0.0, -180.0, -360.0, -540.0]


def test_small_negative_sweep_is_not_full_turn():
    # A very small negative sweep should not be classified as a full turn
    # (the magnitude guard prevents near-zero from being full turn)
    # Small negative value wraps through % 360 to 359.9995, which would trigger
    # the upper tolerance band if magnitude guard didn't prevent it
    small_negative = -0.0005
    angles = frame_angles(2, 0.0, small_negative, clockwise=False)
    # Should be partial arc: step = -0.0005 / (2 - 1) = -0.0005
    assert degrees(angles) == [0.0, -0.0005]
