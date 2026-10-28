"""The View3D sidebar panel."""

import math

import bpy


class RASTERSHEET_PT_panel(bpy.types.Panel):
    bl_label = "RasterSheet"
    bl_idname = "RASTERSHEET_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "RasterSheet"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.rastersheet

        target = layout.box()
        target.label(text="Target")
        obj = context.active_object
        target.label(text=obj.name if obj else "No active object")

        rotation = layout.box()
        rotation.label(text="Rotation")
        rotation.prop(settings, "rotation_axis")
        rotation.prop(settings, "pivot_mode")
        rotation.prop(settings, "frame_count")
        rotation.prop(settings, "clockwise")
        rotation.prop(settings, "start_angle")
        rotation.prop(settings, "sweep_angle")

        camera = layout.box()
        camera.label(text="Camera")
        camera.prop(settings, "camera_mode")
        if settings.camera_mode == "AUTO_ORTHO":
            camera.prop(settings, "azimuth")
            camera.prop(settings, "elevation")
            camera.prop(settings, "camera_margin")
            camera.operator("rastersheet.copy_view", icon="VIEW3D")

        rendering = layout.box()
        rendering.label(text="Rendering")
        rendering.prop(settings, "engine_mode")
        rendering.prop(settings, "lighting_mode")
        if settings.lighting_mode == "MATERIAL_PREVIEW":
            rendering.prop(settings, "studio_light")
        elif settings.lighting_mode == "KEY_LIGHT":
            rendering.prop(settings, "key_elevation")
            rendering.prop(settings, "key_side")
            rendering.prop(settings, "key_strength")
            rendering.prop(settings, "key_ambient")
        elif settings.lighting_mode == "CUSTOM_HDRI":
            rendering.prop(settings, "hdri_path")
            rendering.prop(settings, "hdri_strength")
        rendering.prop(settings, "view_transform_mode")
        rendering.prop(settings, "transparent")
        rendering.prop(settings, "resolution_mode")
        if settings.resolution_mode == "CUSTOM":
            rendering.prop(settings, "resolution_x")
            rendering.prop(settings, "resolution_y")

        stylize = layout.box()
        header = stylize.row()
        header.label(text="Stylize")
        header.operator_menu_enum(
            "rastersheet.apply_preset", "preset", text="Presets", icon="BRUSH_DATA"
        )
        stylize.prop(settings, "stylize_toon")
        if settings.stylize_toon:
            stylize.prop(settings, "toon_bands")
            stylize.prop(settings, "toon_matte")
            stylize.prop(settings, "toon_smooth")
            stylize.prop(settings, "toon_flat_color")
            stylize.prop(settings, "toon_faceted")
            stylize.prop(settings, "toon_rim")
            if settings.toon_rim:
                stylize.prop(settings, "toon_rim_color")
                stylize.prop(settings, "toon_rim_width")
            stylize.prop(settings, "toon_brightness")
            stylize.prop(settings, "toon_saturation")
            stylize.prop(settings, "toon_ink_shadows")
        stylize.prop(settings, "stylize_outline_3d")
        if settings.stylize_outline_3d:
            stylize.prop(settings, "outline_3d_width")
        stylize.prop(settings, "stylize_silhouette")
        if settings.stylize_silhouette:
            stylize.prop(settings, "silhouette_width")
        if settings.stylize_outline_3d or settings.stylize_silhouette:
            stylize.prop(settings, "ink_color")
        stylize.prop(settings, "stylize_glow")
        if settings.stylize_glow:
            stylize.prop(settings, "glow_threshold")
            stylize.prop(settings, "glow_radius")
            stylize.prop(settings, "glow_intensity")
        stylize.prop(settings, "stylize_posterize")
        if settings.stylize_posterize:
            stylize.prop(settings, "posterize_levels")
        stylize.prop(settings, "stylize_pixelate")
        if settings.stylize_pixelate:
            stylize.prop(settings, "pixel_size")
            stylize.prop(settings, "pixel_hard_alpha")

        sheet = layout.box()
        sheet.label(text="Sprite Sheet")
        sheet.prop(settings, "sheet_mode")
        if settings.sheet_mode == "GRID":
            sheet.prop(settings, "columns")
            columns = min(settings.columns, settings.frame_count)
            sheet.label(text=f"Rows: {math.ceil(settings.frame_count / columns)}")

        output = layout.box()
        output.label(text="Output")
        output.prop(settings, "output_dir")
        output.prop(settings, "filename_stem")
        output.prop(settings, "animation_name")
        output.prop(settings, "fps")
        output.prop(settings, "loop")

        export = layout.box()
        export.label(text="Export")
        export.prop(settings, "export_frames")
        export.prop(settings, "export_sheet")
        export.prop(settings, "export_json")
        export.prop(settings, "export_godot")
        if settings.export_godot:
            export.prop(settings, "godot_res_prefix")

        layout.separator()
        row = layout.row(align=True)
        row.operator("rastersheet.render", icon="RENDER_RESULT")
        row.operator("rastersheet.render_still", icon="IMAGE_DATA")
