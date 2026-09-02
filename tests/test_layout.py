import pytest

from rastersheet.core.layout import sheet_layout


def test_grid_derives_rows_and_sheet_size():
    layout = sheet_layout(16, 4, "GRID", 256, 128)
    assert (layout.rows, layout.columns) == (4, 4)
    assert (layout.sheet_width, layout.sheet_height) == (1024, 512)


def test_grid_cells_are_row_major_from_the_top_left():
    layout = sheet_layout(4, 2, "GRID", 10, 20)
    assert [(c.x, c.y) for c in layout.cells] == [(0, 0), (10, 0), (0, 20), (10, 20)]


def test_ragged_last_row_still_places_every_frame():
    layout = sheet_layout(5, 3, "GRID", 10, 10)
    assert layout.rows == 2
    assert len(layout.cells) == 5
    assert (layout.cells[3].x, layout.cells[3].y) == (0, 10)


def test_horizontal_strip_is_one_row():
    layout = sheet_layout(16, 4, "HORIZONTAL", 8, 8)
    assert (layout.rows, layout.columns) == (1, 16)
    assert (layout.sheet_width, layout.sheet_height) == (128, 8)


def test_vertical_strip_is_one_column():
    layout = sheet_layout(16, 4, "VERTICAL", 8, 8)
    assert (layout.rows, layout.columns) == (16, 1)
    assert (layout.sheet_width, layout.sheet_height) == (8, 128)


def test_columns_are_clamped_to_the_frame_count():
    layout = sheet_layout(3, 10, "GRID", 8, 8)
    assert (layout.rows, layout.columns) == (1, 3)


def test_cells_tile_without_overlap():
    layout = sheet_layout(6, 3, "GRID", 4, 4)
    seen = set()
    for cell in layout.cells:
        for x in range(cell.x, cell.x + cell.width):
            for y in range(cell.y, cell.y + cell.height):
                assert (x, y) not in seen
                seen.add((x, y))
    assert len(seen) == 6 * 4 * 4


def test_mode_is_recorded_on_the_layout():
    assert sheet_layout(4, 2, "GRID", 8, 8).mode == "GRID"


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        sheet_layout(4, 2, "SPIRAL", 8, 8)


def test_frame_count_below_two_is_rejected():
    with pytest.raises(ValueError):
        sheet_layout(1, 1, "GRID", 8, 8)
