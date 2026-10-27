import numpy as np

from rastersheet.core.stylize import (
    glow,
    pixelate,
    posterize,
    silhouette_outline,
    stylize_frame,
)


def _canvas(height=32, width=32):
    return np.zeros((height, width, 4), dtype=np.float32)


def _square(color=(1.0, 0.0, 0.0), size=32, lo=12, hi=20):
    image = _canvas(size, size)
    image[lo:hi, lo:hi, :3] = color
    image[lo:hi, lo:hi, 3] = 1.0
    return image


def test_stylize_frame_defaults_are_identity():
    image = np.random.default_rng(0).random((16, 16, 4), dtype=np.float32)
    assert np.array_equal(stylize_frame(image), image)


def test_posterize_quantizes_color_and_keeps_alpha():
    image = _canvas(1, 3)
    image[0, :, 0] = [0.1, 0.4, 0.9]
    image[0, :, 3] = [0.2, 0.5, 1.0]
    out = posterize(image, 2)
    assert out[0, :, 0].tolist() == [0.0, 0.0, 1.0]
    assert np.allclose(out[0, :, 3], [0.2, 0.5, 1.0])


def test_outline_inks_a_ring_without_painting_the_subject():
    out = silhouette_outline(_square(), 2, (0.0, 0.0, 0.0, 1.0))
    # Subject untouched.
    assert np.allclose(out[14, 14], [1.0, 0.0, 0.0, 1.0])
    # Two pixels outside the edge: opaque ink.
    assert np.allclose(out[16, 10], [0.0, 0.0, 0.0, 1.0])
    # Three pixels out: still transparent.
    assert out[16, 9, 3] == 0.0


def test_outline_uses_the_ink_color():
    out = silhouette_outline(_square(), 1, (0.0, 1.0, 1.0))
    assert np.allclose(out[16, 11], [0.0, 1.0, 1.0, 1.0])


def test_glow_spills_light_onto_transparent_background():
    out = glow(_square(color=(0.0, 1.0, 1.0)), 0.5, 6, 1.0)
    halo = out[16, 9]
    assert 0.0 < halo[3] < 1.0
    assert halo[1] > 0.9 and halo[0] < 0.01  # the halo carries the subject's color


def test_glow_does_not_wash_out_the_subject():
    subject = _square(color=(0.0, 1.0, 1.0))
    out = glow(subject, 0.5, 6, 2.0)
    assert np.allclose(out[16, 16], subject[16, 16])


def test_glow_ignores_pixels_below_the_threshold():
    dim = _square(color=(0.3, 0.3, 0.3))
    assert np.allclose(glow(dim, 0.75, 6, 1.0), dim)


def test_pixelate_keeps_size_and_makes_uniform_blocks():
    image = np.random.default_rng(1).random((10, 13, 4), dtype=np.float32)
    image[..., 3] = 1.0
    out = pixelate(image, 4, hard_alpha=False)
    assert out.shape == image.shape
    assert np.allclose(out[0:4, 0:4], out[0, 0])
    # The ragged right-hand block still averages only real pixels.
    assert np.allclose(out[0, 12, :3], image[0:4, 12, :3].mean(axis=0), atol=1e-5)


def test_pixelate_does_not_bleed_transparent_rgb_into_the_edge():
    image = _canvas(2, 2)
    image[0, 0] = [1.0, 0.0, 0.0, 1.0]
    image[1, 1, :3] = [0.0, 1.0, 0.0]  # invisible green: must not show up
    out = pixelate(image, 2, hard_alpha=False)
    assert np.allclose(out[0, 0], [1.0, 0.0, 0.0, 0.25])


def test_pixelate_hard_alpha_snaps_edges():
    image = _canvas(2, 4)
    image[:, 0:2] = [1.0, 1.0, 1.0, 0.6]
    image[:, 2:4] = [1.0, 1.0, 1.0, 0.4]
    out = pixelate(image, 2, hard_alpha=True)
    assert np.allclose(out[0, 0], [1.0, 1.0, 1.0, 1.0])
    assert np.allclose(out[0, 3], [0.0, 0.0, 0.0, 0.0])
