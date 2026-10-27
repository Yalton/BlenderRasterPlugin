"""2D post-processing applied to each rendered frame.

Every function takes and returns a float32 array of shape (height, width, 4)
holding *straight* (unassociated) RGBA in display space -- exactly what
Blender hands back from `Image.pixels` for a PNG it rendered with a
transparent film. Rows are in whatever order the caller uses; nothing here
cares which way is up.

Anything that blends colors (outline compositing, glow, pixel averaging)
works in premultiplied space and converts back, because averaging straight
colors lets the invisible RGB of fully transparent pixels bleed into edges.

Each effect is off at its neutral value (0 levels, 0 width, 0 radius, pixel
size 1), so `stylize_frame` with no arguments returns its input unchanged.
"""

import numpy as np

_EPSILON = 1e-6


def _premultiply(rgba):
    out = rgba.copy()
    out[..., :3] *= out[..., 3:4]
    return out


def _unpremultiply(premultiplied):
    out = premultiplied.copy()
    alpha = out[..., 3:4]
    safe = np.where(alpha > _EPSILON, alpha, 1.0)
    out[..., :3] = np.where(alpha > _EPSILON, out[..., :3] / safe, 0.0)
    return np.clip(out, 0.0, 1.0)


def posterize(rgba, levels):
    """Quantize each color channel to `levels` evenly spaced values.

    Alpha is left alone so antialiased edges stay smooth.
    """
    if levels < 2:
        return rgba
    steps = levels - 1
    out = rgba.copy()
    out[..., :3] = np.round(np.clip(out[..., :3], 0.0, 1.0) * steps) / steps
    return out


def _disk_offsets(radius):
    span = range(-radius, radius + 1)
    return [(dy, dx) for dy in span for dx in span if dy * dy + dx * dx <= radius * radius]


def _max_filter_disk(channel, radius):
    """Grayscale dilation by a disk: each pixel becomes the max within `radius`.

    Operating on the alpha values themselves (not a thresholded mask) keeps
    the outline's outer edge as soft as the render's own antialiasing.
    """
    height, width = channel.shape
    padded = np.pad(channel, radius, mode="constant", constant_values=0.0)
    out = np.zeros_like(channel)
    for dy, dx in _disk_offsets(radius):
        window = padded[radius + dy : radius + dy + height, radius + dx : radius + dx + width]
        np.maximum(out, window, out=out)
    return out


def silhouette_outline(rgba, width, color):
    """Draw a solid ink band `width` pixels wide around the opaque shape.

    The band sits *behind* the original pixels, so the subject itself is
    never painted over; only transparent and partly transparent surroundings
    pick up ink. `color` is RGB or RGBA; its alpha scales the band.
    """
    if width < 1:
        return rgba
    alpha = rgba[..., 3]
    ink_alpha = _max_filter_disk(alpha, int(width))
    ink_rgb = np.asarray(color[:3], dtype=np.float32)
    if len(color) > 3:
        ink_alpha = ink_alpha * float(color[3])

    # Source-over: original on top of the ink layer.
    out_alpha = alpha + ink_alpha * (1.0 - alpha)
    premult_rgb = rgba[..., :3] * alpha[..., None] + ink_rgb * (ink_alpha * (1.0 - alpha))[..., None]

    out = np.empty_like(rgba)
    out[..., :3] = premult_rgb
    out[..., 3] = out_alpha
    return _unpremultiply(out)


def _box_blur_axis(array, radius, axis):
    """Mean over a (2*radius+1) window along `axis`, zero outside the image."""
    if radius < 1:
        return array
    pad = [(0, 0)] * array.ndim
    pad[axis] = (radius + 1, radius)
    summed = np.cumsum(np.pad(array, pad, mode="constant"), axis=axis, dtype=np.float64)
    length = array.shape[axis]
    upper = np.take(summed, np.arange(2 * radius + 1, 2 * radius + 1 + length), axis=axis)
    lower = np.take(summed, np.arange(0, length), axis=axis)
    return ((upper - lower) / (2 * radius + 1)).astype(np.float32)


def _gaussian_ish_blur(array, radius):
    """Three box passes per axis -- a close, cheap stand-in for a Gaussian.

    Each pass uses a third of the radius so the total reach is about `radius`.
    """
    box = max(1, int(round(radius / 3.0)))
    out = array
    for _ in range(3):
        out = _box_blur_axis(out, box, axis=0)
        out = _box_blur_axis(out, box, axis=1)
    return out


def glow(rgba, threshold, radius, intensity):
    """Add a bloom halo around pixels brighter than `threshold`.

    Brightness is measured as the max channel, so a saturated pure color
    (bright cyan, hot magenta) glows as readily as white does.

    The halo sits *behind* the subject: it is added only in proportion to how
    transparent each pixel is. Adding it on top as well would push a
    saturated neon toward white (cyan plus a cyan halo clips its red channel
    up), which is the opposite of the look this is for. Alpha grows so the
    halo shows on a transparent background.
    """
    if radius < 1 or intensity <= 0.0:
        return rgba
    premult = _premultiply(rgba)
    brightness = premult[..., :3].max(axis=-1)
    span = max(1.0 - threshold, _EPSILON)
    weight = np.clip((brightness - threshold) / span, 0.0, 1.0)
    bright = premult[..., :3] * weight[..., None]
    halo = _gaussian_ish_blur(bright, radius) * intensity

    out = np.empty_like(rgba)
    behind = (1.0 - rgba[..., 3])[..., None]
    out[..., :3] = premult[..., :3] + halo * behind
    halo_alpha = np.clip(halo.max(axis=-1), 0.0, 1.0)
    out[..., 3] = rgba[..., 3] + halo_alpha * (1.0 - rgba[..., 3])
    return _unpremultiply(out)


def pixelate(rgba, size, hard_alpha):
    """Average `size` x `size` blocks and repeat them, keeping the frame size.

    The output has the same dimensions as the input, so a sprite sheet's
    layout never changes because of this. A partial block at the right or
    bottom edge averages only the pixels it has. `hard_alpha` snaps each
    block to fully opaque or fully transparent at 50%, the usual pixel-art
    edge.
    """
    if size < 2:
        return rgba
    height, width = rgba.shape[:2]
    rows = -(-height // size)
    cols = -(-width // size)
    premult = _premultiply(rgba)
    padded = np.zeros((rows * size, cols * size, 4), dtype=np.float32)
    padded[:height, :width] = premult
    coverage = np.zeros((rows * size, cols * size), dtype=np.float32)
    coverage[:height, :width] = 1.0

    block_sum = padded.reshape(rows, size, cols, size, 4).sum(axis=(1, 3))
    block_count = coverage.reshape(rows, size, cols, size).sum(axis=(1, 3))
    blocks = block_sum / block_count[..., None]
    if hard_alpha:
        opaque = blocks[..., 3] >= 0.5
        color = np.where(
            blocks[..., 3:4] > _EPSILON, blocks[..., :3] / np.maximum(blocks[..., 3:4], _EPSILON), 0.0
        )
        blocks[..., :3] = np.where(opaque[..., None], color, 0.0)
        blocks[..., 3] = opaque.astype(np.float32)

    expanded = np.repeat(np.repeat(blocks, size, axis=0), size, axis=1)[:height, :width]
    return _unpremultiply(expanded)


def stylize_frame(
    rgba,
    *,
    posterize_levels=0,
    outline_width=0,
    ink_color=(0.0, 0.0, 0.0, 1.0),
    glow_threshold=0.75,
    glow_radius=0,
    glow_intensity=0.0,
    pixel_size=1,
    hard_alpha=False,
):
    """Run every enabled effect in a fixed order.

    Posterize first so the flat bands are what gets outlined and glowed;
    outline before glow so the ink is not bloomed over; pixelate last so the
    outline and halo come out chunky like everything else.
    """
    out = np.asarray(rgba, dtype=np.float32)
    out = posterize(out, posterize_levels)
    out = silhouette_outline(out, outline_width, ink_color)
    out = glow(out, glow_threshold, glow_radius, glow_intensity)
    out = pixelate(out, pixel_size, hard_alpha)
    return out
