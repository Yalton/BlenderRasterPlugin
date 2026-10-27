"""The angle schedule for a sprite sheet's frames."""

import math

# Tolerance for classifying a sweep as a full turn.
# Blender stores rotation properties as float32, which introduces
# rounding error when radians are converted back to degrees.
# For example, radians(360) becomes 360.00001 degrees after round-trip.
# This tolerance must comfortably exceed float32 error (~1e-5 degrees)
# while staying well below any angle a person would type.
_FULL_TURN_TOLERANCE_DEG = 1e-3


def frame_angles(count, start_deg, sweep_deg, clockwise):
    """Return `count` rotation angles in radians.

    A sweep that is a whole non-zero multiple of 360 degrees is a full turn:
    the step is `sweep / count`, so the last frame stops one step short of
    wrapping onto frame 0 and a looping animation has no duplicate frame.

    Any other sweep is a partial arc: the step is `sweep / (count - 1)`, so
    both endpoints are rendered.

    The full turn classification uses floating-point tolerance because
    Blender stores rotation properties as float32, which causes rounding
    error when converting to/from radians. The tolerance is approximately
    1e-3 degrees, which safely exceeds typical float32 error without
    misclassifying human-typed angles.

    A single frame is a still: just the start angle, whatever the sweep.
    """
    if count < 1:
        raise ValueError("frame count must be at least 1")
    if count == 1:
        return [math.radians(start_deg)]

    # Check if sweep is a full turn (whole multiple of 360 degrees)
    # with tolerance for float32 rounding error.
    # The remainder can be near 0 or near 360 depending on rounding direction.
    remainder = sweep_deg % 360.0
    is_full_turn = (
        abs(sweep_deg) > _FULL_TURN_TOLERANCE_DEG and (
            remainder <= _FULL_TURN_TOLERANCE_DEG or
            remainder >= 360.0 - _FULL_TURN_TOLERANCE_DEG
        )
    )

    step = sweep_deg / count if is_full_turn else sweep_deg / (count - 1)
    sign = -1.0 if clockwise else 1.0

    return [math.radians(start_deg + sign * step * index) for index in range(count)]
