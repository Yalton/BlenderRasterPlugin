"""Temporary world construction.

Every mode except SCENE_WORLD builds a fresh world datablock and assigns it to
the scene. The user's own world node tree is never edited.
"""

import math
import os

import bpy
from mathutils import Matrix

from . import snapshot

BLACK = (0.0, 0.0, 0.0, 1.0)
WHITE = (1.0, 1.0, 1.0, 1.0)


def _temp_world(stack):
    world = bpy.data.worlds.new("RasterSheet Temp World")
    snapshot.track_datablock(stack, bpy.data.worlds, world)
    world.use_nodes = True
    return world


def _studio_light_path(settings):
    if settings.studio_light in {"", "NONE"}:
        return None
    try:
        directory = bpy.utils.system_resource("DATAFILES", path="studiolights/world")
    except TypeError:
        return None
    path = os.path.join(directory, settings.studio_light)
    return path if os.path.isfile(path) else None


def _attach_environment(world, stack, image_path, strength):
    image = bpy.data.images.load(image_path, check_existing=False)
    snapshot.track_datablock(stack, bpy.data.images, image)

    tree = world.node_tree
    background = tree.nodes["Background"]
    environment = tree.nodes.new("ShaderNodeTexEnvironment")
    environment.image = image
    tree.links.new(environment.outputs["Color"], background.inputs["Color"])
    background.inputs["Strength"].default_value = strength


def apply_lighting(context, settings, stack):
    scene = context.scene
    mode = settings.lighting_mode

    if mode == "SCENE_WORLD":
        return

    world = _temp_world(stack)
    background = world.node_tree.nodes["Background"]
    background.inputs["Strength"].default_value = 1.0

    if mode == "SCENE_LIGHTS":
        background.inputs["Color"].default_value = BLACK
    elif mode == "KEY_LIGHT":
        # The sun itself needs the resolved camera, so add_key_light places
        # it later; the world here is only the ambient fill.
        level = settings.key_ambient
        background.inputs["Color"].default_value = (level, level, level, 1.0)
    elif mode == "FLAT":
        background.inputs["Color"].default_value = WHITE
    elif mode == "MATERIAL_PREVIEW":
        path = _studio_light_path(settings)
        if path is None:
            background.inputs["Color"].default_value = WHITE
        else:
            _attach_environment(world, stack, path, 1.0)
    elif mode == "CUSTOM_HDRI":
        _attach_environment(
            world, stack, bpy.path.abspath(settings.hdri_path), settings.hdri_strength
        )
    else:
        raise ValueError(f"unknown lighting mode {mode!r}")

    scene.world = world


def key_light_matrix(camera_matrix, elevation_deg, side_deg):
    """A sun orientation relative to the camera.

    A sun shines down its own -Z, as a camera looks down its -Z, so the
    camera's own matrix is a light from straight behind the viewer.
    A negative turn about the camera's X tips the light's source upward
    (so positive elevation = from above), and a turn about its Y swings it
    sideways (negative = from the left).
    """
    return (
        camera_matrix
        @ Matrix.Rotation(math.radians(-elevation_deg), 4, "X")
        @ Matrix.Rotation(math.radians(side_deg), 4, "Y")
    )


def add_key_light(context, settings, stack):
    """Place a temporary sun at a fixed angle to the scene camera.

    Lighting relative to the camera, not the world, means every render --
    every card -- is lit the same way whatever the camera's position, with
    no lamp to place by hand. Other lamps in the scene still contribute.
    """
    scene = context.scene
    light = bpy.data.lights.new("RasterSheet Key Light", "SUN")
    snapshot.track_datablock(stack, bpy.data.lights, light)
    light.energy = settings.key_strength
    sun = bpy.data.objects.new("RasterSheet Key Light", light)
    snapshot.track_datablock(stack, bpy.data.objects, sun)
    scene.collection.objects.link(sun)
    sun.matrix_world = key_light_matrix(
        scene.camera.matrix_world, settings.key_elevation, settings.key_side
    )
    return sun
