"""The per-frame render loop.

This is a generator that yields once per completed frame. V1 drives it to
completion synchronously, but writing it this way means a modal timer operator
can drive the same code later without a rewrite.
"""

import os

import bpy

from ..core.paths import frame_filename


def frame_jobs(context, scene, obj, frame_matrices, frames_dir, stem):
    for index, matrix in enumerate(frame_matrices):
        obj.matrix_world = matrix
        context.view_layer.update()
        scene.render.filepath = os.path.join(frames_dir, frame_filename(stem, index))
        bpy.ops.render.render(write_still=True)
        yield index
