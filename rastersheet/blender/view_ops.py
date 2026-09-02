"""Small helper operators for the panel."""

import bpy
from mathutils import Vector

from .camera import angles_from_direction


class RASTERSHEET_OT_copy_view(bpy.types.Operator):
    bl_idname = "rastersheet.copy_view"
    bl_label = "Copy From Viewport"
    bl_description = "Set azimuth and elevation from the current 3D view direction"

    @classmethod
    def poll(cls, context):
        return context.space_data is not None and context.space_data.type == "VIEW_3D"

    def execute(self, context):
        region_3d = context.space_data.region_3d
        # The view rotation maps camera local +Z onto the direction from the
        # subject toward the viewer, which is the same convention as
        # direction_from().
        direction = region_3d.view_rotation @ Vector((0.0, 0.0, 1.0))
        azimuth, elevation = angles_from_direction(direction)

        settings = context.scene.rastersheet
        settings.azimuth = azimuth
        settings.elevation = elevation
        self.report({"INFO"}, f"Azimuth {azimuth:.1f}, elevation {elevation:.1f}")
        return {"FINISHED"}
