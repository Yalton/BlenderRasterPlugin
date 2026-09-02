"""The angle schedule for a sprite sheet's frames."""

import math


def frame_angles(count, start_deg, sweep_deg, clockwise):
    """Return `count` rotation angles in radians.

    A sweep that is a whole non-zero multiple of 360 degrees is a full turn:
    the step is `sweep / count`, so the last frame stops one step short of
    wrapping onto frame 0 and a looping animation has no duplicate frame.

    Any other sweep is a partial arc: the step is `sweep / (count - 1)`, so
    both endpoints are rendered.
    """
    if count < 2:
        raise ValueError("frame count must be at least 2")

    full_turn = sweep_deg != 0.0 and sweep_deg % 360.0 == 0.0
    step = sweep_deg / count if full_turn else sweep_deg / (count - 1)
    sign = -1.0 if clockwise else 1.0

    return [math.radians(start_deg + sign * step * index) for index in range(count)]
