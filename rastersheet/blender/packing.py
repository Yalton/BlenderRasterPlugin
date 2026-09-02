"""Composite rendered frames into a single sheet image.

Two details decide whether this is correct. First, Blender applies a colorspace
transform when decoding an image and its inverse when encoding, so the sheet
must carry the same colorspace and alpha mode as the frames or every sprite is
silently double-transformed. Second, Blender's pixel buffer is bottom-up while
`core.layout` emits top-left-origin rectangles, so the single flip lives here.
"""

import bpy
import numpy as np


def _read_pixels(image):
    width, height = image.size
    buffer = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(buffer)
    return buffer.reshape(height, width, 4)


def pack_sheet(frame_paths, layout, sheet_path):
    if len(frame_paths) != len(layout.cells):
        raise ValueError(
            f"{len(frame_paths)} frames do not fit {len(layout.cells)} layout cells"
        )

    sheet_buffer = np.zeros((layout.sheet_height, layout.sheet_width, 4), dtype=np.float32)
    colorspace = None
    alpha_mode = None
    loaded = []

    try:
        for cell, path in zip(layout.cells, frame_paths):
            image = bpy.data.images.load(path)
            loaded.append(image)

            if colorspace is None:
                colorspace = image.colorspace_settings.name
                alpha_mode = image.alpha_mode

            width, height = image.size
            if (width, height) != (cell.width, cell.height):
                raise ValueError(
                    f"frame {path} is {width}x{height}, expected {cell.width}x{cell.height}"
                )

            bottom = layout.sheet_height - cell.y - cell.height
            sheet_buffer[bottom : bottom + cell.height, cell.x : cell.x + cell.width] = _read_pixels(
                image
            )

        sheet = bpy.data.images.new(
            "rastersheet_output",
            width=layout.sheet_width,
            height=layout.sheet_height,
            alpha=True,
            float_buffer=False,
        )
        loaded.append(sheet)
        sheet.colorspace_settings.name = colorspace
        sheet.alpha_mode = alpha_mode
        sheet.pixels.foreach_set(sheet_buffer.reshape(-1))
        sheet.file_format = "PNG"
        sheet.filepath_raw = sheet_path
        sheet.save()
    finally:
        for image in loaded:
            bpy.data.images.remove(image)
