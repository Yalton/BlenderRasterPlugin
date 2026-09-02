"""Camera selection and construction."""


def resolve_camera(context, settings, stack, obj):
    """Return the camera to render through.

    In CURRENT mode the scene camera is used untouched. Validation has already
    guaranteed it exists.
    """
    if settings.camera_mode == "CURRENT":
        return context.scene.camera
    raise NotImplementedError(f"camera mode {settings.camera_mode!r} is not implemented yet")
