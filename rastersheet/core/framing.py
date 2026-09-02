"""Orthographic framing.

One scale is computed for the whole sheet, over the **union** of every
frame's camera-space points. A per-frame scale would make the sprite visibly
pump in size as the object rotates, and a maximum of per-frame extents is not
enough: the shell places a single camera at the centre of the union of all
frames, so what that one camera has to cover is the union, not the widest
single pose. The two agree exactly when every frame shares a camera-space
centre (a subject spinning in place); they diverge when the subject orbits,
which is what the default ORIGIN pivot does to any mesh that is not centred
on its object origin.
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
    points = [view @ (matrix @ corner) for matrix in frame_matrices for corner in corners]

    width = max(p.x for p in points) - min(p.x for p in points)
    height = max(p.y for p in points) - min(p.y for p in points)

    return max(width, height * aspect) * margin
