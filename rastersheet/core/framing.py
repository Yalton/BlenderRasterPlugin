"""Orthographic framing.

One scale is computed for the whole sheet, as the maximum requirement across
every frame. A per-frame scale would make the sprite visibly pump in size as
the object rotates.
"""


def required_ortho_scale(corners, camera_matrix, frame_matrices, aspect, margin):
    """The horizontal ortho_scale that contains the object at every angle."""
    if aspect <= 0.0:
        raise ValueError("aspect must be positive")
    if not frame_matrices:
        raise ValueError("at least one frame matrix is required")
    if not corners:
        raise ValueError("at least one bound corner is required")

    view = camera_matrix.inverted()
    needed = 0.0

    for matrix in frame_matrices:
        points = [view @ (matrix @ corner) for corner in corners]
        width = max(p.x for p in points) - min(p.x for p in points)
        height = max(p.y for p in points) - min(p.y for p in points)
        needed = max(needed, width, height * aspect)

    return needed * margin
