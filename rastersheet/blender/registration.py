import bpy

from . import operator, panel, properties, view_ops

CLASSES = (
    properties.RasterSheetSettings,
    operator.RASTERSHEET_OT_render,
    operator.RASTERSHEET_OT_render_still,
    operator.RASTERSHEET_OT_comic_preset,
    view_ops.RASTERSHEET_OT_copy_view,
    panel.RASTERSHEET_PT_panel,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.rastersheet = bpy.props.PointerProperty(
        type=properties.RasterSheetSettings
    )


def unregister():
    del bpy.types.Scene.rastersheet
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
