"""Camera selection and temporary orthographic camera construction.

The view direction is explicit azimuth and elevation rather than an inferred
"desired view". With both at zero the camera sits on the world -Y axis looking
toward +Y, which is Blender's front view.
"""

import math

import bpy
from mathutils import Vector

from ..core.framing import required_ortho_scale
from . import snapshot


def direction_from(azimuth_deg, elevation_deg):
    """The unit vector from the subject toward the camera."""
    azimuth = math.radians(azimuth_deg)
    elevation = math.radians(elevation_deg)
    return Vector(
        (
            math.sin(azimuth) * math.cos(elevation),
            -math.cos(azimuth) * math.cos(elevation),
            math.sin(elevation),
        )
    ).normalized()


def angles_from_direction(direction):
    """Inverse of `direction_from`, in degrees."""
    direction = direction.normalized()
    elevation = math.degrees(math.asin(max(-1.0, min(1.0, direction.z))))
    azimuth = math.degrees(math.atan2(direction.x, -direction.y))
    return azimuth % 360.0, elevation


def _world_points(corners, frame_matrices):
    return [matrix @ corner for matrix in frame_matrices for corner in corners]


def _build_ortho_camera(context, settings, stack, corners, frame_matrices, aspect):
    scene = context.scene

    points = _world_points(corners, frame_matrices)
    low = Vector([min(p[i] for p in points) for i in range(3)])
    high = Vector([max(p[i] for p in points) for i in range(3)])
    center = (low + high) * 0.5
    radius = max((p - center).length for p in points) or 1.0

    direction = direction_from(settings.azimuth, settings.elevation)
    distance = radius * 4.0

    data = bpy.data.cameras.new("RasterSheet Temp Camera")
    snapshot.track_datablock(stack, bpy.data.cameras, data)
    data.type = "ORTHO"
    data.sensor_fit = "HORIZONTAL"

    camera = bpy.data.objects.new("RasterSheet Temp Camera", data)
    snapshot.track_datablock(stack, bpy.data.objects, camera)
    scene.collection.objects.link(camera)

    # Build the transform as a local matrix and assign it whole. Mutating
    # camera.matrix_world in place relies on write-back behavior that is easy to
    # get wrong; a local Matrix has no such ambiguity.
    matrix = direction.to_track_quat("Z", "Y").to_matrix().to_4x4()
    matrix.translation = center + direction * distance

    # Aiming at the world-space bounds center does not guarantee the object is
    # centered in camera space, so measure the residual offset and slide the
    # camera sideways by exactly that much. Without this, a margin barely over
    # 1.0 can clip one edge.
    view = matrix.inverted()
    local = [view @ point for point in points]
    offset_x = (max(p.x for p in local) + min(p.x for p in local)) * 0.5
    offset_y = (max(p.y for p in local) + min(p.y for p in local)) * 0.5
    matrix.translation = matrix.translation + (
        matrix.to_3x3() @ Vector((offset_x, offset_y, 0.0))
    )
    camera.matrix_world = matrix

    view = matrix.inverted()
    local = [view @ point for point in points]
    near = -max(p.z for p in local)
    far = -min(p.z for p in local)
    data.clip_start = max(near - 0.001, 1e-4)
    data.clip_end = far + 0.001

    data.ortho_scale = required_ortho_scale(
        corners, matrix, frame_matrices, aspect, settings.camera_margin
    )
    return camera


def resolve_camera(context, settings, stack, obj, corners, frame_matrices, aspect):
    """Return the camera to render through."""
    if settings.camera_mode == "CURRENT":
        return context.scene.camera
    if settings.camera_mode == "AUTO_ORTHO":
        return _build_ortho_camera(context, settings, stack, corners, frame_matrices, aspect)
    raise ValueError(f"unknown camera mode {settings.camera_mode!r}")
