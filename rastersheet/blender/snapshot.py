"""Capture and restore scene state.

Every mutation registers its own restore callback at the moment it is applied,
rather than being collected into one dictionary up front. If setup fails
partway through, only what was actually changed is unwound, in reverse order.
"""

import contextlib


def guard(stack, owner, attr):
    """Register the current value of `owner.attr` for restoration."""
    original = getattr(owner, attr)
    stack.callback(setattr, owner, attr, original)


def _set_matrix(obj, matrix):
    obj.matrix_world = matrix


def guard_matrix(stack, obj):
    stack.callback(_set_matrix, obj, obj.matrix_world.copy())


def _remove(collection, datablock):
    try:
        collection.remove(datablock)
    except (ReferenceError, RuntimeError):
        pass


def track_datablock(stack, collection, datablock):
    """Remove a temporary datablock when the snapshot unwinds."""
    stack.callback(_remove, collection, datablock)


RENDER_ATTRS = (
    "engine",
    "resolution_x",
    "resolution_y",
    "resolution_percentage",
    "film_transparent",
    "filepath",
)

IMAGE_SETTINGS_ATTRS = ("file_format", "color_mode", "color_depth")

VIEW_SETTINGS_ATTRS = ("view_transform", "look", "exposure")


@contextlib.contextmanager
def scene_snapshot(scene, objects):
    """Guard everything the add-on is allowed to touch, then yield the stack."""
    with contextlib.ExitStack() as stack:
        for attr in RENDER_ATTRS:
            guard(stack, scene.render, attr)
        for attr in IMAGE_SETTINGS_ATTRS:
            guard(stack, scene.render.image_settings, attr)
        for attr in VIEW_SETTINGS_ATTRS:
            guard(stack, scene.view_settings, attr)
        guard(stack, scene, "camera")
        guard(stack, scene, "world")
        for obj in objects:
            guard_matrix(stack, obj)
        yield stack
