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
    except (ReferenceError, RuntimeError) as exc:
        # A partly-torn-down datablock (already freed, or in a state the
        # collection refuses to remove) is a legitimate case -- but silently
        # swallowing it would leave an orphan in bpy.data with no trace, the
        # exact failure this module exists to prevent. Say so.
        print(f"rastersheet: failed to remove datablock {datablock!r}: {exc!r}")


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

# ExitStack unwinds LIFO, so whichever attribute is registered *last* here
# restores *first*. file_format governs which color_mode/color_depth values
# are legal (e.g. OPEN_EXR allows depth '16'/'32' but not PNG's '8'), and
# view_transform governs which `look` values are legal -- so the governing
# attribute goes last in each tuple, on purpose, to restore before its
# dependents. Reordering these to look "natural" reintroduces a scene-
# corruption path: restoring a dependent while its governor is still at the
# temporary value can raise, aborting the unwind with the dependent stuck.
IMAGE_SETTINGS_ATTRS = ("color_mode", "color_depth", "file_format")

VIEW_SETTINGS_ATTRS = ("exposure", "look", "view_transform")


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
