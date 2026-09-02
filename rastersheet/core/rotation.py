"""Per-frame world transforms.

Frames are produced by composing world matrices rather than by assigning
`rotation_quaternion`. That gives one code path for local and world axes,
makes the pivot a natural parameter, and never touches `rotation_mode`.
"""

from mathutils import Matrix, Vector

_UNIT = {
    "X": Vector((1.0, 0.0, 0.0)),
    "Y": Vector((0.0, 1.0, 0.0)),
    "Z": Vector((0.0, 0.0, 1.0)),
}


def axis_vector(axis, base_matrix):
    """Resolve an axis identifier to a normalized world-space direction."""
    space, _, letter = axis.partition("_")
    if letter not in _UNIT:
        raise ValueError(f"unknown rotation axis {axis!r}")

    unit = _UNIT[letter]
    if space == "WORLD":
        return unit.copy()
    if space != "LOCAL":
        raise ValueError(f"unknown rotation axis {axis!r}")

    world = base_matrix.to_3x3() @ unit
    if world.length == 0.0:
        raise ValueError("object transform collapses the rotation axis")
    return world.normalized()


def frame_matrix(base_matrix, axis_world, angle, pivot):
    """The object's world matrix for one frame."""
    rotation = Matrix.Rotation(angle, 4, axis_world)
    return Matrix.Translation(pivot) @ rotation @ Matrix.Translation(-pivot) @ base_matrix
