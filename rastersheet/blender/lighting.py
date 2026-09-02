"""Temporary world construction.

Every mode except SCENE_WORLD builds a fresh world datablock and assigns it to
the scene. The user's own world node tree is never edited.
"""

import os

import bpy

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
