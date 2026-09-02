import bpy

from . import operator, panel, properties

CLASSES = (
    properties.RasterSheetSettings,
    operator.RASTERSHEET_OT_render,
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
