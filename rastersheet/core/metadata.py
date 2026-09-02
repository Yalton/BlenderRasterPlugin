"""The engine-agnostic JSON sidecar."""


def build_metadata(
    image_name,
    layout,
    animation_name,
    fps,
    loop,
    axis,
    start_deg,
    sweep_deg,
    clockwise,
):
    return {
        "image": image_name,
        "frame_count": len(layout.cells),
        "columns": layout.columns,
        "rows": layout.rows,
        "frame_width": layout.frame_width,
        "frame_height": layout.frame_height,
        "sheet_width": layout.sheet_width,
        "sheet_height": layout.sheet_height,
        "layout": layout.mode,
        "fps": fps,
        "loop": loop,
        "animation": animation_name,
        "rotation": {
            "axis": axis,
            "start_angle": start_deg,
            "sweep_angle": sweep_deg,
            "clockwise": clockwise,
        },
    }
