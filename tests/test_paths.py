from rastersheet.core.paths import build_output_paths, frame_filename, sanitize_stem


def test_frame_filenames_are_one_based_and_zero_padded():
    assert frame_filename("nuke", 0) == "nuke_0001.png"
    assert frame_filename("nuke", 15) == "nuke_0016.png"


def test_sanitize_replaces_unsafe_characters():
    assert sanitize_stem("my sprite/v2") == "my_sprite_v2"


def test_sanitize_trims_leading_and_trailing_separators():
    assert sanitize_stem("  .._spin_..  ") == "spin"


def test_sanitize_falls_back_when_nothing_survives():
    assert sanitize_stem("///") == "sprite"


def test_output_paths_are_derived_from_the_sanitized_stem():
    paths = build_output_paths("/out", "nuke spin")
    assert paths.stem == "nuke_spin"
    assert paths.frames_dir == "/out/nuke_spin_frames"
    assert paths.sheet == "/out/nuke_spin.png"
    assert paths.json == "/out/nuke_spin.json"
    assert paths.tres == "/out/nuke_spin.tres"
