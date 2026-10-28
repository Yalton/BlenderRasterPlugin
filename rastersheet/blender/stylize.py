"""Optional comic-style looks: toon materials, 3D ink outlines, 2D post.

The material-level effects (toon shading, inverted-hull outline) follow the
same rule as everything else in this add-on: nothing the user authored is
edited in place. Toon shading renders with *copies* of the user's materials
swapped into the material slots; the outline adds a temporary material slot
and a temporary Solidify modifier. Every one of those is registered on the
snapshot stack the moment it happens, so the scene unwinds exactly.

They apply to every visible, renderable object, not only the rotating
target: the camera sees the whole scene, and a card composed of several
objects (a bullet plus its trail) should come out in one consistent style.

The 2D effects run after rendering, on each frame PNG, before packing.
"""

import bpy
import numpy as np

from ..core.stylize import stylize_frame
from . import snapshot

MATERIAL_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT"}


def styled_objects(context):
    return [
        obj
        for obj in context.view_layer.objects
        if obj.type in MATERIAL_TYPES and not obj.hide_render and obj.visible_get()
    ]


def is_eevee(engine):
    return engine.startswith("BLENDER_EEVEE")


# --- Toon shading -----------------------------------------------------------


def _surface_link(tree):
    output = tree.get_output_node("ALL") or tree.get_output_node("EEVEE")
    if output is None:
        return None, None
    surface = output.inputs["Surface"]
    return output, (surface.links[0] if surface.links else None)


def _math(tree, operation, value):
    node = tree.nodes.new("ShaderNodeMath")
    node.operation = operation
    node.inputs[1].default_value = value
    return node


def _toonify(material, bands):
    """Rewire `material`'s surface through a banded Shader to RGB.

    Shader to RGB captures the fully lit color (Eevee only); its HSV value is
    rounded to the nearest of `bands` steps and re-emitted, so hue and
    saturation survive while shading collapses to flat tiers.

    The rounding happens on a gamma-2.2 curve, not on the linear value.
    Linear steps of 1/3 land at roughly 61% and 84% display brightness, so
    every band crowds into the bright half and the render washes out;
    perceptual steps come out evenly spaced on screen. Values above 1
    (emissive parts) pass through the same curve and stay above 1.
    """
    tree = material.node_tree
    output, link = _surface_link(tree)
    if link is None:
        return False
    shader_socket = link.from_socket

    to_rgb = tree.nodes.new("ShaderNodeShaderToRGB")
    tree.links.new(shader_socket, to_rgb.inputs["Shader"])

    separate = tree.nodes.new("ShaderNodeSeparateColor")
    separate.mode = "HSV"
    tree.links.new(to_rgb.outputs["Color"], separate.inputs["Color"])

    encode = _math(tree, "POWER", 1.0 / 2.2)
    scale = _math(tree, "MULTIPLY", float(bands))
    snap = tree.nodes.new("ShaderNodeMath")
    snap.operation = "ROUND"
    unscale = _math(tree, "DIVIDE", float(bands))
    decode = _math(tree, "POWER", 2.2)
    tree.links.new(separate.outputs[2], encode.inputs[0])
    tree.links.new(encode.outputs[0], scale.inputs[0])
    tree.links.new(scale.outputs[0], snap.inputs[0])
    tree.links.new(snap.outputs[0], unscale.inputs[0])
    tree.links.new(unscale.outputs[0], decode.inputs[0])

    combine = tree.nodes.new("ShaderNodeCombineColor")
    combine.mode = "HSV"
    tree.links.new(separate.outputs[0], combine.inputs[0])
    tree.links.new(separate.outputs[1], combine.inputs[1])
    tree.links.new(decode.outputs[0], combine.inputs[2])

    emission = tree.nodes.new("ShaderNodeEmission")
    emission.inputs["Strength"].default_value = 1.0
    tree.links.new(combine.outputs["Color"], emission.inputs["Color"])

    # Keep the material's own transparency: Shader to RGB reports it as alpha.
    transparent = tree.nodes.new("ShaderNodeBsdfTransparent")
    mix = tree.nodes.new("ShaderNodeMixShader")
    tree.links.new(to_rgb.outputs["Alpha"], mix.inputs[0])
    tree.links.new(transparent.outputs[0], mix.inputs[1])
    tree.links.new(emission.outputs[0], mix.inputs[2])

    tree.links.new(mix.outputs[0], output.inputs["Surface"])
    return True


def _default_material(stack):
    material = bpy.data.materials.new("RasterSheet Default")
    _track(stack, bpy.data.materials, material)
    material.use_nodes = True
    return material


def _track(stack, collection, datablock):
    snapshot.track_datablock(stack, collection, datablock)


def _append_slot(stack, data, material):
    data.materials.append(material)
    stack.callback(data.materials.pop)


def apply_toon(stack, objects, bands):
    """Swap toon copies of every material into the objects' slots.

    Returns warnings for materials that could not be converted (no node
    tree output wired to Surface); those keep rendering as authored.
    """
    warnings = []
    copies = {}
    defaulted = set()

    for obj in objects:
        data = obj.data
        if not any(slot.material for slot in obj.material_slots) and data not in defaulted:
            # No material at all renders Blender's built-in grey, which no
            # node tree can be inserted into. Give it a real one for the run.
            defaulted.add(data)
            if not data.materials:
                _append_slot(stack, data, _default_material(stack))
            else:
                for index, existing in enumerate(data.materials):
                    if existing is None:
                        stack.callback(data.materials.__setitem__, index, None)
                        data.materials[index] = _default_material(stack)

        for slot in obj.material_slots:
            original = slot.material
            if original is None:
                continue
            if original not in copies:
                copy = original.copy()
                _track(stack, bpy.data.materials, copy)
                copy.use_nodes = True
                if not _toonify(copy, bands):
                    warnings.append(f"Toon shading skipped material {original.name!r}: no Surface output")
                copies[original] = copy
            snapshot.guard(stack, slot, "material")
            slot.material = copies[original]

    return warnings


# --- Inverted-hull ink outline ---------------------------------------------


def _outline_material(stack, color):
    """Black where the hull's inside faces the camera, see-through elsewhere.

    The hull is the object pushed outward with flipped normals, so its near
    side is back-facing and must vanish, and only the far side -- visible as
    a rim around the silhouette and wherever surfaces overlap -- draws ink.
    The Backfacing switch does this in both Eevee and Cycles; backface
    culling is set as well so Eevee skips the hidden side outright.
    """
    material = bpy.data.materials.new("RasterSheet Outline")
    _track(stack, bpy.data.materials, material)
    material.use_nodes = True
    material.use_backface_culling = True
    if hasattr(material, "use_transparent_shadow"):
        material.use_transparent_shadow = True
    tree = material.node_tree
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputMaterial")

    geometry = tree.nodes.new("ShaderNodeNewGeometry")
    ink = tree.nodes.new("ShaderNodeEmission")
    ink.inputs["Color"].default_value = (color[0], color[1], color[2], 1.0)
    ink.inputs["Strength"].default_value = 1.0
    clear = tree.nodes.new("ShaderNodeBsdfTransparent")
    mix = tree.nodes.new("ShaderNodeMixShader")
    tree.links.new(geometry.outputs["Backfacing"], mix.inputs[0])
    tree.links.new(ink.outputs[0], mix.inputs[1])
    tree.links.new(clear.outputs[0], mix.inputs[2])
    tree.links.new(mix.outputs[0], output.inputs["Surface"])
    return material


def apply_outline(stack, objects, width, color):
    """Give every mesh a temporary inverted hull `width` world units thick."""
    warnings = []
    meshes = [obj for obj in objects if obj.type == "MESH"]
    skipped = [obj.name for obj in objects if obj.type != "MESH"]
    if skipped:
        warnings.append(f"Ink outline only supports meshes; skipped {', '.join(sorted(skipped))}")
    if not meshes:
        return warnings

    material = _outline_material(stack, color)
    extended = set()
    for obj in meshes:
        data = obj.data
        if data not in extended:
            extended.add(data)
            if not data.materials:
                # The outline must not become slot 0, or the object's own
                # faces would draw with it. An empty slot 0 keeps them on
                # Blender's default material, as before.
                _append_slot(stack, data, None)
            _append_slot(stack, data, material)

        modifier = obj.modifiers.new("RasterSheet Outline", "SOLIDIFY")
        stack.callback(obj.modifiers.remove, modifier)
        scale = sum(abs(component) for component in obj.matrix_world.to_scale()) / 3.0
        modifier.thickness = width / max(scale, 1e-6)
        modifier.offset = 1.0
        modifier.use_flip_normals = True
        modifier.use_rim = False
        # Even thickness divides by the angle between a vertex's faces, so at
        # a near-degenerate corner (a thin lever, a bevel seam) one vertex
        # shoots out to many times the width and draws a large black spike.
        # Plain offset never exceeds the width.
        modifier.use_even_offset = False
        # Blender clamps a shell's material index to the last slot, and the
        # outline is the last slot, so an offset past every existing index
        # sends every shell face to it regardless of the faces' own slots.
        modifier.material_offset = len(data.materials)

    return warnings


# --- 2D post -----------------------------------------------------------------


def post_options(settings):
    """The keyword arguments for `stylize_frame`, or None when nothing is on."""
    options = {}
    if settings.stylize_posterize:
        options["posterize_levels"] = settings.posterize_levels
    if settings.stylize_silhouette:
        options["outline_width"] = settings.silhouette_width
        options["ink_color"] = tuple(settings.ink_color)
    if settings.stylize_glow:
        options["glow_threshold"] = settings.glow_threshold
        options["glow_radius"] = settings.glow_radius
        options["glow_intensity"] = settings.glow_intensity
    if settings.stylize_pixelate:
        options["pixel_size"] = settings.pixel_size
        options["hard_alpha"] = settings.pixel_hard_alpha
    return options or None


def post_process(frame_paths, options):
    """Rewrite each frame PNG in place with the 2D effects applied.

    The image is read and written back through Blender with its own
    colorspace and alpha mode untouched, which is the same round trip
    `packing` relies on: the values seen here are the stored display values,
    straight alpha.
    """
    for path in frame_paths:
        image = bpy.data.images.load(path, check_existing=False)
        try:
            width, height = image.size
            buffer = np.empty(width * height * 4, dtype=np.float32)
            image.pixels.foreach_get(buffer)
            styled = stylize_frame(buffer.reshape(height, width, 4), **options)
            image.pixels.foreach_set(np.ascontiguousarray(styled, dtype=np.float32).reshape(-1))
            image.filepath_raw = path
            image.file_format = "PNG"
            image.save()
        finally:
            bpy.data.images.remove(image)
