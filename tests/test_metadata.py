from rastersheet.core.layout import sheet_layout
from rastersheet.core.metadata import build_metadata


def test_metadata_matches_the_documented_shape():
    layout = sheet_layout(16, 4, "GRID", 256, 128)
    document = build_metadata(
        image_name="nuke_spin.png",
        layout=layout,
        animation_name="spin",
        fps=12.0,
        loop=True,
        axis="LOCAL_Y",
        start_deg=0.0,
        sweep_deg=360.0,
        clockwise=True,
    )
    assert document == {
        "image": "nuke_spin.png",
        "frame_count": 16,
        "columns": 4,
        "rows": 4,
        "frame_width": 256,
        "frame_height": 128,
        "sheet_width": 1024,
        "sheet_height": 512,
        "layout": "GRID",
        "fps": 12.0,
        "loop": True,
        "animation": "spin",
        "rotation": {
            "axis": "LOCAL_Y",
            "start_angle": 0.0,
            "sweep_angle": 360.0,
            "clockwise": True,
        },
    }


def test_strip_layout_is_reported():
    layout = sheet_layout(4, 4, "HORIZONTAL", 8, 8)
    document = build_metadata(
        image_name="strip.png",
        layout=layout,
        animation_name="walk",
        fps=8.0,
        loop=False,
        axis="WORLD_Z",
        start_deg=45.0,
        sweep_deg=90.0,
        clockwise=False,
    )
    assert document["layout"] == "HORIZONTAL"
    assert document["rows"] == 1
    assert document["columns"] == 4
    assert document["loop"] is False
    assert document["rotation"]["clockwise"] is False
