"""Sprite sheet geometry.

Cell rectangles use a top-left origin, which is what every consumer of the
metadata expects. Blender's bottom-up pixel buffer is the shell's problem.
"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Cell:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class SheetLayout:
    rows: int
    columns: int
    frame_width: int
    frame_height: int
    mode: str
    cells: tuple

    @property
    def sheet_width(self):
        return self.columns * self.frame_width

    @property
    def sheet_height(self):
        return self.rows * self.frame_height


def sheet_layout(frame_count, columns, mode, frame_width, frame_height):
    if frame_count < 2:
        raise ValueError("frame count must be at least 2")
    if frame_width < 1 or frame_height < 1:
        raise ValueError("frame dimensions must be positive")

    if mode == "HORIZONTAL":
        columns = frame_count
    elif mode == "VERTICAL":
        columns = 1
    elif mode == "GRID":
        if columns < 1:
            raise ValueError("columns must be at least 1")
        columns = min(columns, frame_count)
    else:
        raise ValueError(f"unknown sheet mode {mode!r}")

    rows = math.ceil(frame_count / columns)
    cells = tuple(
        Cell(
            x=(index % columns) * frame_width,
            y=(index // columns) * frame_height,
            width=frame_width,
            height=frame_height,
        )
        for index in range(frame_count)
    )
    return SheetLayout(rows, columns, frame_width, frame_height, mode, cells)
