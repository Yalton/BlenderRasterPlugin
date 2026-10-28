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

from dataclasses import dataclass

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


@dataclass(frozen=True)
class ToonLook:
    """Every toon setting. The defaults are the neutral, plain-banding look."""

    bands: int = 3
    brightness: float = 1.0
    saturation: float = 1.0
    ink_shadows: float = 0.0
    matte: bool = False
    smooth: bool = False
    flat_color: bool = False
    faceted: bool = False
    rim: bool = False
    rim_color: tuple = (0.3, 0.9, 1.0)
    rim_width: float = 0.3


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


def _make_matte(tree):
    """Zero Metallic on every Principled BSDF in `tree`, cutting any texture
    driving it.

    Metal has no diffuse response: lit by one lamp it renders black apart
    from a highlight, and lit by an HDRI it mirrors the HDRI instead of
    showing its form. Banded shading needs light falling on the surface, so
    a matte render is what toon shading usually wants. Only called on the
    temporary copy, never the authored material.
    """
    for node in tree.nodes:
        if node.bl_idname != "ShaderNodeBsdfPrincipled":
            continue
        metallic = node.inputs.get("Metallic")
        if metallic is None:
            continue
        for link in list(metallic.links):
            tree.links.remove(link)
        metallic.default_value = 0.0


# Inputs whose textures add per-pixel lighting noise rather than color.
_DETAIL_INPUTS = {
    "ShaderNodeOutputMaterial": ("Displacement",),
}
_BSDF_DETAIL_INPUTS = ("Normal", "Roughness")


def _drop_surface_detail(tree):
    """Cut the textures that perturb lighting: normal, bump, roughness.

    Normal maps, displacement (which Eevee renders as bump) and roughness
    maps put per-pixel noise into the *lighting*, and banding turns that
    noise into speckle along every band edge. Without them the bands follow
    the model's actual shape, which is what reads as inked. Color textures
    are kept: those are the model's paint, not its lighting. A cut
    roughness falls back to the socket's own unlinked value.
    Only called on the temporary copy, never the authored material.
    """
    for node in tree.nodes:
        if node.bl_idname.startswith("ShaderNodeBsdf"):
            names = _BSDF_DETAIL_INPUTS
        else:
            names = _DETAIL_INPUTS.get(node.bl_idname, ())
        for name in names:
            socket = node.inputs.get(name)
            if socket is None:
                continue
            for link in list(socket.links):
                tree.links.remove(link)


def _srgb_to_linear(values):
    return np.where(values <= 0.04045, values / 12.92, ((values + 0.055) / 1.055) ** 2.4)


def _average_color(image):
    """The image's mean color as a linear RGBA tuple, or None if unreadable.

    `Image.pixels` holds the stored values -- sRGB-encoded for a color
    texture -- so they are linearized before averaging, because a BSDF's
    Base Color socket is linear. Averaging the encoded values would come out
    too dark.
    """
    width, height = image.size
    if width == 0 or height == 0:
        return None
    buffer = np.empty(width * height * image.channels, dtype=np.float32)
    image.pixels.foreach_get(buffer)
    pixels = buffer.reshape(-1, image.channels)
    rgb = pixels[:, :3] if image.channels >= 3 else np.repeat(pixels[:, :1], 3, axis=1)
    if image.colorspace_settings.name.lower().startswith("srgb"):
        rgb = _srgb_to_linear(rgb)
    mean = rgb.mean(axis=0)
    return (float(mean[0]), float(mean[1]), float(mean[2]), 1.0)


def _flatten_color(tree):
    """Replace each image texture feeding a Base Color with its mean color.

    Photographic texture -- grime, scratches, color noise -- banded into
    tiers reads as a photocopy rather than a drawing. Inked art fills each
    part with one color, and a texture's mean is the part's color. Inputs
    driven by anything other than an image (procedural textures, mixes)
    are left alone: there is no single color to read off them.
    """
    for node in tree.nodes:
        if not node.bl_idname.startswith("ShaderNodeBsdf"):
            continue
        base = node.inputs.get("Base Color") or node.inputs.get("Color")
        if base is None or not base.is_linked:
            continue
        source = base.links[0].from_node
        if source.bl_idname != "ShaderNodeTexImage" or source.image is None:
            continue
        color = _average_color(source.image)
        if color is None:
            continue
        tree.links.remove(base.links[0])
        base.default_value = color


def _facet(tree):
    """Shade every BSDF with the true face normal instead of the smoothed one.

    Banding a smooth sphere gives soft concentric blobs; banding flat faces
    gives crisp planes, which is how inked hard-surface art reads. Done in
    the shader so the mesh itself is never touched. Replaces any normal map,
    which would put the smooth detail back.
    """
    geometry = tree.nodes.new("ShaderNodeNewGeometry")
    for node in list(tree.nodes):
        if not node.bl_idname.startswith("ShaderNodeBsdf"):
            continue
        normal = node.inputs.get("Normal")
        if normal is not None:
            tree.links.new(geometry.outputs["True Normal"], normal)


def _toonify(material, look):
    """Rewire `material`'s surface through a banded Shader to RGB.

    Shader to RGB captures the fully lit color (Eevee only); its HSV value is
    rounded to the nearest of `bands` steps and re-emitted, so hue and
    saturation survive while shading collapses to flat tiers.

    The rounding happens on a gamma-2.2 curve, not on the linear value.
    Linear steps of 1/3 land at roughly 61% and 84% display brightness, so
    every band crowds into the bright half and the render washes out;
    perceptual steps come out evenly spaced on screen. Values above 1
    (emissive parts) pass through the same curve and stay above 1.

    The comic controls all act on that perceptual value, after banding, so
    each one moves the bands evenly on screen: `brightness` scales them,
    `ink_shadows` turns every band at or below it solid black (the large
    spot blacks of inked comics), and `saturation` scales color intensity.
    Their neutral values (1, 0, 1) leave the banded result unchanged.
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
    bands, brightness, saturation, ink_shadows = (
        look.bands,
        look.brightness,
        look.saturation,
        look.ink_shadows,
    )
    scale = _math(tree, "MULTIPLY", float(bands))
    snap = tree.nodes.new("ShaderNodeMath")
    snap.operation = "ROUND"
    unscale = _math(tree, "DIVIDE", float(bands))
    brighten = _math(tree, "MULTIPLY", float(brightness))
    # 1 above the ink threshold, 0 at or below it; multiplying by it inks
    # the shadow bands. A threshold of 0 keeps everything but true black.
    lit = _math(tree, "GREATER_THAN", float(ink_shadows))
    ink = tree.nodes.new("ShaderNodeMath")
    ink.operation = "MULTIPLY"
    decode = _math(tree, "POWER", 2.2)
    tree.links.new(separate.outputs[2], encode.inputs[0])
    tree.links.new(encode.outputs[0], scale.inputs[0])
    tree.links.new(scale.outputs[0], snap.inputs[0])
    tree.links.new(snap.outputs[0], unscale.inputs[0])
    tree.links.new(unscale.outputs[0], brighten.inputs[0])
    tree.links.new(unscale.outputs[0], lit.inputs[0])
    tree.links.new(brighten.outputs[0], ink.inputs[0])
    tree.links.new(lit.outputs[0], ink.inputs[1])
    tree.links.new(ink.outputs[0], decode.inputs[0])

    saturate = _math(tree, "MULTIPLY", float(saturation))
    saturate.use_clamp = True
    tree.links.new(separate.outputs[1], saturate.inputs[0])

    combine = tree.nodes.new("ShaderNodeCombineColor")
    combine.mode = "HSV"
    tree.links.new(separate.outputs[0], combine.inputs[0])
    tree.links.new(saturate.outputs[0], combine.inputs[1])
    tree.links.new(decode.outputs[0], combine.inputs[2])

    color_socket = combine.outputs["Color"]
    if look.rim:
        color_socket = _add_rim(tree, color_socket, look)

    emission = tree.nodes.new("ShaderNodeEmission")
    emission.inputs["Strength"].default_value = 1.0
    tree.links.new(color_socket, emission.inputs["Color"])

    # Keep the material's own transparency: Shader to RGB reports it as alpha.
    transparent = tree.nodes.new("ShaderNodeBsdfTransparent")
    mix = tree.nodes.new("ShaderNodeMixShader")
    tree.links.new(to_rgb.outputs["Alpha"], mix.inputs[0])
    tree.links.new(transparent.outputs[0], mix.inputs[1])
    tree.links.new(emission.outputs[0], mix.inputs[2])

    tree.links.new(mix.outputs[0], output.inputs["Surface"])
    return True


def _add_rim(tree, color_socket, look):
    """Paint a hard band of `rim_color` where the surface turns away from view.

    Layer Weight's Facing output is 0 facing the camera and 1 at grazing
    angles; everything past `1 - rim_width` gets the rim. It is a hard step,
    not a blend, so it reads as a drawn edge highlight like a comic's rim
    light rather than a soft Fresnel glow. The rim color is emitted as-is,
    so a bright one also feeds Glow.
    """
    facing = tree.nodes.new("ShaderNodeLayerWeight")
    facing.inputs["Blend"].default_value = 0.5
    edge = _math(tree, "GREATER_THAN", 1.0 - float(look.rim_width))
    tree.links.new(facing.outputs["Facing"], edge.inputs[0])

    mix = tree.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    tree.links.new(edge.outputs[0], mix.inputs["Factor"])
    a_input = next(s for s in mix.inputs if s.identifier == "A_Color")
    b_input = next(s for s in mix.inputs if s.identifier == "B_Color")
    tree.links.new(color_socket, a_input)
    b_input.default_value = (*look.rim_color[:3], 1.0)
    return next(s for s in mix.outputs if s.identifier == "Result_Color")


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


def apply_toon(stack, objects, look):
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
                if look.matte:
                    _make_matte(copy.node_tree)
                if look.smooth:
                    _drop_surface_detail(copy.node_tree)
                if look.flat_color:
                    _flatten_color(copy.node_tree)
                if look.faceted:
                    _facet(copy.node_tree)
                if not _toonify(copy, look):
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


def toon_look(settings):
    return ToonLook(
        bands=settings.toon_bands,
        brightness=settings.toon_brightness,
        saturation=settings.toon_saturation,
        ink_shadows=settings.toon_ink_shadows,
        matte=settings.toon_matte,
        smooth=settings.toon_smooth,
        flat_color=settings.toon_flat_color,
        faceted=settings.toon_faceted,
        rim=settings.toon_rim,
        rim_color=tuple(settings.toon_rim_color),
        rim_width=settings.toon_rim_width,
    )


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
