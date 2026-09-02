"""RasterSheet: render a rotating object into a sprite sheet."""


def register():
    from .blender import registration

    registration.register()


def unregister():
    from .blender import registration

    registration.unregister()
