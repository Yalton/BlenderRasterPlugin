"""Headless Blender smoke tests. Run with: blender -b -P tests_blender/run_smoke.py"""

import sys
import traceback

import bpy

MODULE = "bl_ext.user_default.rastersheet"


def enable_addon():
    bpy.ops.preferences.addon_enable(module=MODULE)


CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


@check
def test_addon_enables():
    assert MODULE in bpy.context.preferences.addons


@check
def test_settings_are_attached_to_the_scene():
    settings = bpy.context.scene.rastersheet
    assert settings is not None


@check
def test_every_property_round_trips():
    settings = bpy.context.scene.rastersheet
    settings.frame_count = 8
    settings.columns = 3
    settings.rotation_axis = "WORLD_Z"
    settings.camera_mode = "AUTO_ORTHO"
    settings.sheet_mode = "VERTICAL"
    settings.lighting_mode = "FLAT"
    settings.view_transform_mode = "AGX"
    settings.engine_mode = "EEVEE"
    settings.pivot_mode = "BOUNDS_CENTER"
    settings.filename_stem = "probe"
    settings.fps = 24.0
    assert settings.frame_count == 8
    assert settings.rotation_axis == "WORLD_Z"
    assert settings.view_transform_mode == "AGX"
    assert settings.filename_stem == "probe"
    assert abs(settings.fps - 24.0) < 1e-6


@check
def test_panel_is_registered():
    assert hasattr(bpy.types, "RASTERSHEET_PT_panel")


@check
def test_studio_light_enum_is_populated():
    # bl_rna.properties[...].enum_items only reflects Blender's own C-level
    # dynamic enums (and even those just report a NONE placeholder -- see
    # view_transform_mode's docstring in properties.py). For a Python itemsf
    # callback like studio_light, Blender calls the function when the
    # property is read, filling the module-level cache the callback
    # populates; that cache is what we can actually assert against here.
    settings = bpy.context.scene.rastersheet
    _ = settings.studio_light
    from bl_ext.user_default.rastersheet.blender.properties import _STUDIO_LIGHT_CACHE

    assert len(_STUDIO_LIGHT_CACHE) >= 1


def main():
    enable_addon()
    for fn in CHECKS:
        fn()
        print(f"  ok  {fn.__name__}")
    print("SMOKE OK")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        print("SMOKE FAIL")
        sys.exit(1)
