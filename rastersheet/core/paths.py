"""Output filenames and derived paths.

`output_dir` must already be an absolute filesystem path. Blender-relative
paths such as `//sprite_output/` are resolved by the shell with
`bpy.path.abspath` before reaching this module.
"""

import os
import re
from dataclasses import dataclass

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_stem(stem):
    cleaned = _UNSAFE.sub("_", stem.strip()).strip("._-")
    return cleaned or "sprite"


def frame_filename(stem, index):
    return f"{stem}_{index + 1:04d}.png"


@dataclass(frozen=True)
class OutputPaths:
    stem: str
    frames_dir: str
    sheet: str
    json: str
    tres: str


def build_output_paths(output_dir, stem):
    stem = sanitize_stem(stem)
    return OutputPaths(
        stem=stem,
        frames_dir=os.path.join(output_dir, f"{stem}_frames"),
        sheet=os.path.join(output_dir, f"{stem}.png"),
        json=os.path.join(output_dir, f"{stem}.json"),
        tres=os.path.join(output_dir, f"{stem}.tres"),
    )
