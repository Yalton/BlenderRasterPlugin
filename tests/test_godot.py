from rastersheet.core.layout import sheet_layout
from rastersheet.core.godot import sprite_frames_tres

EXPECTED_TWO_FRAMES = '''[gd_resource type="SpriteFrames" load_steps=4 format=3]

[ext_resource type="Texture2D" path="res://probe.png" id="1_tex"]

[sub_resource type="AtlasTexture" id="AtlasTexture_0"]
atlas = ExtResource("1_tex")
region = Rect2(0, 0, 32, 32)

[sub_resource type="AtlasTexture" id="AtlasTexture_1"]
atlas = ExtResource("1_tex")
region = Rect2(32, 0, 32, 32)

[resource]
animations = [{
"frames": [{"duration": 1.0, "texture": SubResource("AtlasTexture_0")}, {"duration": 1.0, "texture": SubResource("AtlasTexture_1")}],
"loop": true,
"name": &"spin",
"speed": 12.0
}]
'''


def test_two_frame_resource_matches_the_golden_text():
    layout = sheet_layout(2, 2, "GRID", 32, 32)
    text = sprite_frames_tres("res://probe.png", layout, "spin", 12.0, True)
    assert text == EXPECTED_TWO_FRAMES


def test_load_steps_is_frame_count_plus_two():
    layout = sheet_layout(16, 4, "GRID", 8, 8)
    text = sprite_frames_tres("res://a.png", layout, "spin", 12.0, True)
    assert "load_steps=18" in text


def test_loop_false_is_written_lowercase():
    layout = sheet_layout(2, 2, "GRID", 8, 8)
    text = sprite_frames_tres("res://a.png", layout, "spin", 12.0, False)
    assert '"loop": false,' in text


def test_regions_follow_the_layout_cells():
    layout = sheet_layout(4, 2, "GRID", 10, 20)
    text = sprite_frames_tres("res://a.png", layout, "spin", 12.0, True)
    assert "region = Rect2(0, 0, 10, 20)" in text
    assert "region = Rect2(10, 0, 10, 20)" in text
    assert "region = Rect2(0, 20, 10, 20)" in text
    assert "region = Rect2(10, 20, 10, 20)" in text


def test_a_quote_in_the_animation_name_is_escaped():
    # animation_name is free text straight from the panel -- unlike
    # filename_stem, nothing sanitizes it. An unescaped `"` closes the string
    # literal early and Godot rejects the whole resource, silently as far as
    # the add-on is concerned.
    layout = sheet_layout(2, 2, "GRID", 8, 8)
    text = sprite_frames_tres("res://a.png", layout, 'sp"in', 12.0, True)
    assert '"name": &"sp\\"in",' in text
    # And the literal is still closed exactly once: an unescaped quote would
    # leave a bare `"` inside it.
    assert 'sp"in' not in text.replace('\\"', "")


def test_a_backslash_in_the_texture_path_is_escaped():
    # The texture path is godot_res_prefix (user-typed) joined to the stem, so
    # a Windows-style separator reaches it unsanitized.
    layout = sheet_layout(2, 2, "GRID", 8, 8)
    text = sprite_frames_tres("res://sprites\\a.png", layout, "spin", 12.0, True)
    assert 'path="res://sprites\\\\a.png"' in text


def test_escaping_leaves_ordinary_names_untouched():
    layout = sheet_layout(2, 2, "GRID", 32, 32)
    text = sprite_frames_tres("res://probe.png", layout, "spin", 12.0, True)
    assert text == EXPECTED_TWO_FRAMES
